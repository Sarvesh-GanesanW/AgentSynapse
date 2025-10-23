import boto3
from boto3.dynamodb.conditions import Key, Attr
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import AgentNotFound
from schemas import AgentConfig, AgentType, TenantContext

logger = getLogger(__name__)


class AgentRegistry:
    def __init__(self):
        self._dynamodb = None
        self._table = None
        self._cache = {}

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
            self._table = self._dynamodb.Table(settings.dynamodb.tableAgentConfig)
        return self._table

    def _convertToDecimal(self, obj):
        """Convert float and int values to Decimal for DynamoDB"""
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, int):
            return Decimal(obj)
        elif isinstance(obj, dict):
            return {k: self._convertToDecimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convertToDecimal(item) for item in obj]
        return obj

    async def register(self, agent: AgentConfig) -> str:
        table = self._getTable()

        item = {
            "pk": f"TENANT#{agent.tenantContext.tenantId}",
            "sk": f"AGENT#{agent.id}",
            "id": agent.id,
            "name": agent.name,
            "type": agent.type.value,
            "description": agent.description,
            "systemPrompt": agent.systemPrompt,
            "temperature": Decimal(str(agent.temperature)),
            "maxTokens": Decimal(agent.maxTokens),
            "toolIds": agent.toolIds,
            "isAsync": agent.isAsync,
            "timeoutSeconds": Decimal(agent.timeoutSeconds),
            "customSettings": self._convertToDecimal(agent.customSettings),
            "tenantId": agent.tenantContext.tenantId,
            "userId": agent.tenantContext.userId,
            "createdAt": agent.createdAt.isoformat(),
            "updatedAt": agent.updatedAt.isoformat()
        }

        try:
            table.put_item(Item=item)
            self._cache[f"{agent.tenantContext.tenantId}:{agent.id}"] = agent
            logger.info("agent_registered", agentId=agent.id, agentType=agent.type.value)
            return agent.id

        except Exception as e:
            logger.error("agent_registration_error", error=str(e), agentId=agent.id)
            raise

    async def get(self, agentId: str, tenantContext: TenantContext) -> AgentConfig:
        cacheKey = f"{tenantContext.tenantId}:{agentId}"

        if cacheKey in self._cache:
            return self._cache[cacheKey]

        table = self._getTable()

        try:
            response = table.get_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}",
                    "sk": f"AGENT#{agentId}"
                }
            )

            if "Item" not in response:
                logger.warning("agent_not_found", agentId=agentId, tenantId=tenantContext.tenantId)
                raise AgentNotFound(agentId)

            item = response["Item"]
            agent = self._itemToAgentConfig(item, tenantContext)
            self._cache[cacheKey] = agent
            return agent

        except Exception as e:
            logger.error("agent_get_error", error=str(e), agentId=agentId)
            if isinstance(e, AgentNotFound):
                raise
            raise AgentNotFound(agentId)

    async def getByType(
        self,
        agentType: AgentType,
        tenantContext: TenantContext
    ) -> Optional[AgentConfig]:
        table = self._getTable()

        try:
            response = table.query(
                KeyConditionExpression=Key("pk").eq(f"TENANT#{tenantContext.tenantId}"),
                FilterExpression=Attr("type").eq(agentType.value),
                Limit=1
            )

            items = response.get("Items", [])

            if not items:
                return None

            return self._itemToAgentConfig(items[0], tenantContext)

        except Exception as e:
            logger.error("agent_get_by_type_error", error=str(e), agentType=agentType.value)
            return None

    async def list(
        self,
        tenantContext: TenantContext,
        agentType: Optional[AgentType] = None
    ) -> List[AgentConfig]:
        table = self._getTable()

        try:
            queryParams = {
                "KeyConditionExpression": Key("pk").eq(f"TENANT#{tenantContext.tenantId}")
            }

            if agentType:
                queryParams["FilterExpression"] = Attr("type").eq(agentType.value)

            response = table.query(**queryParams)
            items = response.get("Items", [])

            return [self._itemToAgentConfig(item, tenantContext) for item in items]

        except Exception as e:
            logger.error("agent_list_error", error=str(e), tenantId=tenantContext.tenantId)
            return []

    async def update(self, agentId: str, updates: dict, tenantContext: TenantContext) -> bool:
        table = self._getTable()

        updateExpr = "SET "
        exprAttrValues = {}
        exprAttrNames = {}

        for key, value in updates.items():
            updateExpr += f"#{key} = :{key}, "
            exprAttrNames[f"#{key}"] = key
            exprAttrValues[f":{key}"] = self._convertToDecimal(value)

        updateExpr += "#updatedAt = :updatedAt"
        exprAttrNames["#updatedAt"] = "updatedAt"
        exprAttrValues[":updatedAt"] = datetime.utcnow().isoformat()

        try:
            table.update_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}",
                    "sk": f"AGENT#{agentId}"
                },
                UpdateExpression=updateExpr,
                ExpressionAttributeNames=exprAttrNames,
                ExpressionAttributeValues=exprAttrValues
            )

            cacheKey = f"{tenantContext.tenantId}:{agentId}"
            if cacheKey in self._cache:
                del self._cache[cacheKey]

            logger.info("agent_updated", agentId=agentId)
            return True

        except Exception as e:
            logger.error("agent_update_error", error=str(e), agentId=agentId)
            return False

    async def delete(self, agentId: str, tenantContext: TenantContext) -> bool:
        table = self._getTable()

        try:
            table.delete_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}",
                    "sk": f"AGENT#{agentId}"
                }
            )

            cacheKey = f"{tenantContext.tenantId}:{agentId}"
            if cacheKey in self._cache:
                del self._cache[cacheKey]

            logger.info("agent_deleted", agentId=agentId)
            return True

        except Exception as e:
            logger.error("agent_delete_error", error=str(e), agentId=agentId)
            return False

    def _itemToAgentConfig(self, item: dict, tenantContext: TenantContext) -> AgentConfig:
        # Use model_construct to bypass validation for already-validated data from database
        return AgentConfig.model_construct(
            id=item["id"],
            name=item["name"],
            type=AgentType(item["type"]),
            description=item["description"],
            systemPrompt=item["systemPrompt"],
            temperature=float(item["temperature"]),
            maxTokens=int(item["maxTokens"]),
            toolIds=item.get("toolIds", []),
            tenantContext=tenantContext,
            isAsync=item.get("isAsync", False),
            timeoutSeconds=int(item.get("timeoutSeconds", 300)),
            customSettings=item.get("customSettings", {}),
            createdAt=datetime.fromisoformat(item["createdAt"]),
            updatedAt=datetime.fromisoformat(item["updatedAt"])
        )

    def clearCache(self):
        self._cache.clear()
        logger.info("agent_registry_cache_cleared")


agentRegistry = AgentRegistry()
