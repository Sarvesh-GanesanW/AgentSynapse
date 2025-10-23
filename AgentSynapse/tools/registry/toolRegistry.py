import boto3
from boto3.dynamodb.conditions import Key, Attr
from typing import List, Dict, Any, Optional
from datetime import datetime
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import InvalidToolDefinition, ToolNotFound
from schemas import ToolDefinition, TenantContext, ToolPermission
from tools.versioning.toolVersioning import toolVersioning, ToolReleaseType

logger = getLogger(__name__)


class ToolRegistry:
    def __init__(self):
        self._dynamodb = None
        self._table = None
        self._localCache = {}

    def _getTable(self):
        if not self._table:
            resourceArgs = {
                "region_name": settings.aws.region,
                "aws_access_key_id": settings.aws.accessKeyId,
                "aws_secret_access_key": settings.aws.secretAccessKey
            }
            if settings.dynamodb.endpointUrl:
                resourceArgs["endpoint_url"] = settings.dynamodb.endpointUrl

            self._dynamodb = boto3.resource("dynamodb", **resourceArgs)
            self._table = self._dynamodb.Table(settings.dynamodb.tableToolRegistry)
        return self._table

    async def register(self, tool: ToolDefinition) -> str:
        toolVersioning.ensureVersionAvailable(tool.name, tool.tenantId, tool.version)

        table = self._getTable()

        item = {
            "pk": f"TENANT#{tool.tenantId}",
            "sk": f"TOOL#{tool.name}#VERSION#{tool.version}",
            "id": tool.id,
            "name": tool.name,
            "version": tool.version,
            "description": tool.description,
            "inputSchema": tool.inputSchema,
            "permission": tool.permission.value,
            "tenantId": tool.tenantId,
            "isActive": tool.isActive,
            "requiresAuth": tool.requiresAuth,
            "createdAt": tool.createdAt.isoformat(),
            "updatedAt": tool.updatedAt.isoformat()
        }

        if tool.outputSchema:
            item["outputSchema"] = tool.outputSchema

        if tool.codeS3Key:
            item["codeS3Key"] = tool.codeS3Key

        if tool.yamlConfig:
            item["yamlConfig"] = tool.yamlConfig

        try:
            table.put_item(Item=item)
            self._localCache[f"{tool.tenantId}:{tool.name}:{tool.version}"] = tool
            logger.info("tool_registered", toolName=tool.name, version=tool.version)
            toolVersioning.recordVersionRegistration(tool.tenantId, tool.name)
            return tool.id

        except Exception as e:
            logger.error("tool_registration_error", error=str(e), toolName=tool.name)
            raise InvalidToolDefinition(f"Failed to register tool: {str(e)}", tool.name)

    async def get(
        self,
        toolName: str,
        tenantContext: TenantContext,
        version: str = "1.0.0"
    ) -> ToolDefinition:
        if version == "latest":
            latestVersion = toolVersioning.getLatestVersion(
                toolName,
                tenantContext.tenantId,
                includePublic=True
            )
            if not latestVersion:
                logger.warning("tool_latest_version_not_found", toolName=toolName, tenantId=tenantContext.tenantId)
                raise ToolNotFound(toolName)
            version = latestVersion

        cacheKey = f"{tenantContext.tenantId}:{toolName}:{version}"

        if cacheKey in self._localCache:
            return self._localCache[cacheKey]

        table = self._getTable()

        try:
            response = table.query(
                KeyConditionExpression=Key("pk").eq(f"TENANT#{tenantContext.tenantId}") &
                                      Key("sk").eq(f"TOOL#{toolName}#VERSION#{version}")
            )

            items = response.get("Items", [])

            if not items:
                publicTools = await self._getPublicTools(toolName, version)
                if publicTools:
                    return publicTools[0]
                logger.warning(
                    "tool_not_found",
                    toolName=toolName,
                    version=version,
                    tenantId=tenantContext.tenantId
                )
                raise ToolNotFound(f"{toolName}:{version}")

            item = items[0]
            tool = self._itemToToolDefinition(item)
            self._localCache[cacheKey] = tool
            return tool

        except Exception as e:
            logger.error("tool_get_error", error=str(e), toolName=toolName)
            if isinstance(e, ToolNotFound):
                raise
            raise ToolNotFound(toolName)

    async def _getPublicTools(self, toolName: str, version: str) -> List[ToolDefinition]:
        table = self._getTable()

        try:
            response = table.query(
                IndexName="ToolNameIndex",
                KeyConditionExpression=Key("name").eq(toolName),
                FilterExpression=Attr("permission").eq(ToolPermission.PUBLIC.value) &
                                Attr("version").eq(version) &
                                Attr("isActive").eq(True)
            )

            items = response.get("Items", [])
            return [self._itemToToolDefinition(item) for item in items]

        except Exception as e:
            logger.error("public_tools_query_error", error=str(e))
            return []

    def _itemToToolDefinition(self, item: Dict[str, Any]) -> ToolDefinition:
        return ToolDefinition(
            id=item["id"],
            name=item["name"],
            version=item["version"],
            description=item["description"],
            inputSchema=item["inputSchema"],
            outputSchema=item.get("outputSchema"),
            permission=ToolPermission(item["permission"]),
            tenantId=item["tenantId"],
            codeS3Key=item.get("codeS3Key"),
            yamlConfig=item.get("yamlConfig"),
            isActive=item.get("isActive", True),
            requiresAuth=item.get("requiresAuth", True),
            createdAt=datetime.fromisoformat(item["createdAt"]),
            updatedAt=datetime.fromisoformat(item["updatedAt"])
        )

    async def list(
        self,
        tenantContext: TenantContext,
        permission: Optional[ToolPermission] = None,
        isActive: bool = True
    ) -> List[ToolDefinition]:
        table = self._getTable()

        try:
            keyCondition = Key("pk").eq(f"TENANT#{tenantContext.tenantId}")
            filterExpression = Attr("isActive").eq(isActive)

            if permission:
                filterExpression = filterExpression & Attr("permission").eq(permission.value)

            response = table.query(
                KeyConditionExpression=keyCondition,
                FilterExpression=filterExpression
            )

            items = response.get("Items", [])
            return [self._itemToToolDefinition(item) for item in items]

        except Exception as e:
            logger.error("tool_list_error", error=str(e), tenantId=tenantContext.tenantId)
            return []

    async def deactivate(
        self,
        toolName: str,
        tenantContext: TenantContext,
        version: str = "1.0.0"
    ) -> bool:
        if version == "latest":
            latestVersion = toolVersioning.getLatestVersion(
                toolName,
                tenantContext.tenantId,
                includePublic=False
            )
            if not latestVersion:
                return False
            version = latestVersion

        table = self._getTable()

        try:
            table.update_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}",
                    "sk": f"TOOL#{toolName}#VERSION#{version}"
                },
                UpdateExpression="SET isActive = :false, updatedAt = :now",
                ExpressionAttributeValues={
                    ":false": False,
                    ":now": datetime.utcnow().isoformat()
                }
            )

            cacheKey = f"{tenantContext.tenantId}:{toolName}:{version}"
            if cacheKey in self._localCache:
                del self._localCache[cacheKey]

            logger.info("tool_deactivated", toolName=toolName, version=version)
            toolVersioning.recordVersionDeactivation(tenantContext.tenantId, toolName)
            return True

        except Exception as e:
            logger.error("tool_deactivate_error", error=str(e), toolName=toolName)
            return False

    async def getToolsForAgent(
        self,
        toolIds: List[str],
        tenantContext: TenantContext
    ) -> List[ToolDefinition]:
        tools = []

        for toolId in toolIds:
            parts = toolId.split(":")
            toolName = parts[0]
            version = parts[1] if len(parts) > 1 else "1.0.0"

            if version == "latest":
                resolvedVersion = toolVersioning.getLatestVersion(
                    toolName,
                    tenantContext.tenantId,
                    includePublic=True
                )
                if resolvedVersion:
                    version = resolvedVersion

            try:
                tool = await self.get(toolName, tenantContext, version)
                tools.append(tool)
            except ToolNotFound:
                logger.warning(
                    "agent_tool_missing",
                    toolName=toolName,
                    version=version,
                    tenantId=tenantContext.tenantId
                )

        return tools

    def clearCache(self):
        self._localCache.clear()
        toolVersioning.clearCache()
        logger.info("tool_registry_cache_cleared")

    async def getVersionHistory(
        self,
        toolName: str,
        tenantContext: TenantContext,
        includePublic: bool = True,
        includeInactive: bool = True
    ) -> Dict[str, Any]:
        history = toolVersioning.getVersionHistory(
            toolName,
            tenantContext.tenantId,
            includePublic=includePublic,
            includeInactive=includeInactive
        )

        return {
            "toolName": toolName,
            "versions": history
        }

    async def getNextVersion(
        self,
        toolName: str,
        tenantContext: TenantContext,
        releaseType: str = "patch",
        includePublic: bool = True
    ) -> Dict[str, Any]:
        try:
            releaseEnum = ToolReleaseType(releaseType.lower())
        except ValueError:
            raise InvalidToolDefinition(
                f"Unsupported release type '{releaseType}'. Use one of: "
                f"{', '.join([r.value for r in ToolReleaseType])}",
                toolName=toolName
            )

        version = toolVersioning.getNextVersion(
            toolName,
            tenantContext.tenantId,
            releaseEnum,
            includePublic=includePublic
        )

        return {
            "toolName": toolName,
            "releaseType": releaseEnum.value,
            "nextVersion": version
        }


toolRegistry = ToolRegistry()
