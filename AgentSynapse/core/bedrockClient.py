import boto3
import json
from typing import Dict, Any, List, Optional, AsyncIterator
from aioboto3 import Session
from botocore.exceptions import ClientError
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import AgentExecutionError
from utils.serialization import DecimalEncoder

logger = getLogger(__name__)


class BedrockClient:
    def __init__(self):
        self.modelId = settings.aws.bedrockModelId
        self.region = settings.aws.region
        self._client = None
        self._asyncSession = None

    def _getClient(self):
        if not self._client:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                aws_access_key_id=settings.aws.accessKeyId,
                aws_secret_access_key=settings.aws.secretAccessKey
            )
        return self._client

    async def _getAsyncClient(self):
        if not self._asyncSession:
            self._asyncSession = Session()
        return self._asyncSession.client(
            "bedrock-runtime",
            region_name=self.region,
            aws_access_key_id=settings.aws.accessKeyId,
            aws_secret_access_key=settings.aws.secretAccessKey
        )

    def invokeModel(
        self,
        messages: List[Dict[str, Any]],
        systemPrompt: Optional[str] = None,
        temperature: float = 0.7,
        maxTokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        stopSequences: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        client = self._getClient()

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "max_tokens": maxTokens,
            "temperature": temperature,
        }

        if systemPrompt:
            body["system"] = systemPrompt

        if tools:
            body["tools"] = tools

        if stopSequences:
            body["stop_sequences"] = stopSequences

        try:
            response = client.invoke_model(
                modelId=self.modelId,
                body=json.dumps(body, cls=DecimalEncoder)
            )

            responseBody = json.loads(response["body"].read())
            return responseBody

        except ClientError as e:
            logger.error("bedrock_invoke_error", error=str(e))
            raise AgentExecutionError(
                f"Bedrock invocation failed: {str(e)}",
                details={"modelId": self.modelId}
            )

    async def invokeModelAsync(
        self,
        messages: List[Dict[str, Any]],
        systemPrompt: Optional[str] = None,
        temperature: float = 0.7,
        maxTokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        stopSequences: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        async with await self._getAsyncClient() as client:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": messages,
                "max_tokens": maxTokens,
                "temperature": temperature,
            }

            if systemPrompt:
                body["system"] = systemPrompt

            if tools:
                body["tools"] = tools

            if stopSequences:
                body["stop_sequences"] = stopSequences

            try:
                response = await client.invoke_model(
                    modelId=self.modelId,
                    body=json.dumps(body, cls=DecimalEncoder)
                )

                responseBody = json.loads(await response["body"].read())
                return responseBody

            except ClientError as e:
                logger.error("bedrock_async_invoke_error", error=str(e))
                raise AgentExecutionError(
                    f"Bedrock async invocation failed: {str(e)}",
                    details={"modelId": self.modelId}
                )

    async def invokeModelStream(
        self,
        messages: List[Dict[str, Any]],
        systemPrompt: Optional[str] = None,
        temperature: float = 0.7,
        maxTokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        async with await self._getAsyncClient() as client:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": messages,
                "max_tokens": maxTokens,
                "temperature": temperature,
            }

            if systemPrompt:
                body["system"] = systemPrompt

            if tools:
                body["tools"] = tools

            try:
                response = await client.invoke_model_with_response_stream(
                    modelId=self.modelId,
                    body=json.dumps(body, cls=DecimalEncoder)
                )

                stream = response.get("body")
                if stream:
                    async for event in stream:
                        chunk = event.get("chunk")
                        if chunk:
                            chunkData = json.loads(chunk.get("bytes").decode())
                            yield chunkData

            except ClientError as e:
                logger.error("bedrock_stream_error", error=str(e))
                raise AgentExecutionError(
                    f"Bedrock streaming failed: {str(e)}",
                    details={"modelId": self.modelId}
                )

    def countTokens(self, text: str) -> int:
        return len(text) // 4

    def formatMessages(
        self,
        userMessage: str,
        conversationHistory: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        messages = []

        if conversationHistory:
            messages.extend(conversationHistory)

        messages.append({
            "role": "user",
            "content": userMessage
        })

        return messages

    def formatToolResult(self, toolUseId: str, toolResult: Any) -> Dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": toolUseId,
                    "content": json.dumps(toolResult, cls=DecimalEncoder) if not isinstance(toolResult, str) else toolResult
                }
            ]
        }

    def extractToolCalls(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        toolCalls = []
        content = response.get("content", [])

        for block in content:
            if block.get("type") == "tool_use":
                toolCalls.append({
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input", {})
                })

        return toolCalls

    def extractTextResponse(self, response: Dict[str, Any]) -> str:
        content = response.get("content", [])

        for block in content:
            if block.get("type") == "text":
                return block.get("text", "")

        return ""


bedrockClient = BedrockClient()
