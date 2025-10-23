import boto3
import json
import importlib.util
import sys
from typing import Dict, Any, Optional
from pathlib import Path
import tempfile
import httpx
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import ToolExecutionError, UnauthorizedAccess
from schemas import ToolDefinition, TenantContext

logger = getLogger(__name__)


class ToolExecutor:
    def __init__(self):
        self._s3 = None
        self._httpClient = httpx.AsyncClient(timeout=30.0)

    def _getS3(self):
        if not self._s3:
            self._s3 = boto3.client(
                "s3",
                region_name=settings.aws.region,
                aws_access_key_id=settings.aws.accessKeyId,
                aws_secret_access_key=settings.aws.secretAccessKey
            )
        return self._s3

    async def execute(
        self,
        tool: ToolDefinition,
        toolInput: Dict[str, Any],
        tenantContext: TenantContext,
        authToken: Optional[str] = None
    ) -> Any:
        if tool.requiresAuth and not authToken:
            raise UnauthorizedAccess(
                "Tool requires authentication",
                resource=tool.name
            )

        if not tool.isActive:
            raise ToolExecutionError(
                f"Tool {tool.name} is not active",
                toolName=tool.name
            )

        try:
            if tool.yamlConfig:
                result = await self._executeYamlTool(tool, toolInput, tenantContext, authToken)
            elif tool.codeS3Key:
                result = await self._executeCodeTool(tool, toolInput, tenantContext, authToken)
            else:
                raise ToolExecutionError(
                    f"Tool {tool.name} has no execution config",
                    toolName=tool.name
                )

            logger.info("tool_executed", toolName=tool.name, tenantId=tenantContext.tenantId)
            return result

        except Exception as e:
            logger.error("tool_execution_error", error=str(e), toolName=tool.name)
            raise ToolExecutionError(
                f"Tool execution failed: {str(e)}",
                toolName=tool.name,
                details={"input": toolInput}
            )

    async def _executeYamlTool(
        self,
        tool: ToolDefinition,
        toolInput: Dict[str, Any],
        tenantContext: TenantContext,
        authToken: Optional[str] = None
    ) -> Any:
        config = tool.yamlConfig

        if config.get("type") == "http":
            return await self._executeHttpTool(config, toolInput, authToken)
        elif config.get("type") == "lambda":
            return await self._executeLambdaTool(config, toolInput, tenantContext)
        else:
            raise ToolExecutionError(
                f"Unsupported YAML tool type: {config.get('type')}",
                toolName=tool.name
            )

    async def _executeHttpTool(
        self,
        config: Dict[str, Any],
        toolInput: Dict[str, Any],
        authToken: Optional[str] = None
    ) -> Any:
        url = config.get("url")
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})

        if authToken:
            headers["Authorization"] = f"Bearer {authToken}"

        if method == "GET":
            response = await self._httpClient.get(url, params=toolInput, headers=headers)
        elif method == "POST":
            response = await self._httpClient.post(url, json=toolInput, headers=headers)
        elif method == "PUT":
            response = await self._httpClient.put(url, json=toolInput, headers=headers)
        else:
            raise ToolExecutionError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()

    async def _executeLambdaTool(
        self,
        config: Dict[str, Any],
        toolInput: Dict[str, Any],
        tenantContext: TenantContext
    ) -> Any:
        lambdaClient = boto3.client(
            "lambda",
            region_name=settings.aws.region,
            aws_access_key_id=settings.aws.accessKeyId,
            aws_secret_access_key=settings.aws.secretAccessKey
        )

        functionName = config.get("functionName")

        payload = {
            "input": toolInput,
            "tenantContext": {
                "tenantId": tenantContext.tenantId,
                "userId": tenantContext.userId,
                "orgId": tenantContext.orgId
            }
        }

        response = lambdaClient.invoke(
            FunctionName=functionName,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )

        responsePayload = json.loads(response["Payload"].read())

        if response.get("FunctionError"):
            raise ToolExecutionError(
                f"Lambda execution failed: {responsePayload}",
                details={"functionName": functionName}
            )

        return responsePayload

    async def _executeCodeTool(
        self,
        tool: ToolDefinition,
        toolInput: Dict[str, Any],
        tenantContext: TenantContext,
        authToken: Optional[str] = None
    ) -> Any:
        s3 = self._getS3()

        response = s3.get_object(
            Bucket=settings.s3.bucketToolCode,
            Key=tool.codeS3Key
        )

        code = response["Body"].read().decode("utf-8")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmpFile:
            tmpFile.write(code)
            tmpFilePath = tmpFile.name

        try:
            spec = importlib.util.spec_from_file_location("tool_module", tmpFilePath)
            module = importlib.util.module_from_spec(spec)
            sys.modules["tool_module"] = module
            spec.loader.exec_module(module)

            if not hasattr(module, "execute"):
                raise ToolExecutionError(
                    "Tool code must have an 'execute' function",
                    toolName=tool.name
                )

            context = {
                "tenantContext": tenantContext,
                "authToken": authToken,
                "toolName": tool.name
            }

            result = await module.execute(toolInput, context)
            return result

        finally:
            Path(tmpFilePath).unlink(missing_ok=True)
            if "tool_module" in sys.modules:
                del sys.modules["tool_module"]

    def formatForBedrock(self, tool: ToolDefinition) -> Dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        }

    async def close(self):
        await self._httpClient.aclose()


toolExecutor = ToolExecutor()
