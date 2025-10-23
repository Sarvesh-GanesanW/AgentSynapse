import boto3
from boto3.dynamodb.conditions import Key, Attr
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import MemoryError
from schemas import EpisodicMemoryRecord, TenantContext, MemorySource, MemoryType
from memory.baseMemoryManager import BaseMemoryManager

logger = getLogger(__name__)


class DynamoDBEpisodicMemory(BaseMemoryManager):
    def __init__(self):
        self._dynamodb = None
        self._table = None

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
            self._table = self._dynamodb.Table(settings.dynamodb.tableEpisodic)
        return self._table

    def _toItem(self, record: EpisodicMemoryRecord) -> Dict[str, Any]:
        item = {
            "pk": f"TENANT#{record.tenantId}#USER#{record.userId}",
            "sk": f"SESSION#{record.sessionId}#TIME#{record.createdAt.isoformat()}#ID#{record.id}",
            "id": record.id,
            "tenantId": record.tenantId,
            "userId": record.userId,
            "sessionId": record.sessionId,
            "agentId": record.agentId,
            "content": record.content,
            "outcome": record.outcome,
            "source": record.source.value,
            "confidenceScore": Decimal(str(record.confidenceScore)),
            "importance": Decimal(str(record.importance)),
            "toolsUsed": record.toolsUsed,
            "tags": record.tags,
            "contextData": record.contextData,
            "createdAt": record.createdAt.isoformat(),
            "updatedAt": record.updatedAt.isoformat(),
            "ttl": int((datetime.utcnow() + timedelta(days=settings.memory.episodicRetentionDays)).timestamp())
        }

        if record.sentiment:
            item["sentiment"] = record.sentiment

        if record.expiresAt:
            item["expiresAt"] = record.expiresAt.isoformat()

        return item

    def _fromItem(self, item: Dict[str, Any]) -> EpisodicMemoryRecord:
        return EpisodicMemoryRecord(
            id=item["id"],
            tenantId=item["tenantId"],
            userId=item["userId"],
            sessionId=item["sessionId"],
            agentId=item["agentId"],
            memoryType=MemoryType.EPISODIC,
            content=item["content"],
            outcome=item["outcome"],
            source=MemorySource(item["source"]),
            confidenceScore=float(item["confidenceScore"]),
            importance=float(item["importance"]),
            toolsUsed=item.get("toolsUsed", []),
            tags=item.get("tags", []),
            contextData=item.get("contextData", {}),
            sentiment=item.get("sentiment"),
            createdAt=datetime.fromisoformat(item["createdAt"]),
            updatedAt=datetime.fromisoformat(item["updatedAt"]),
            expiresAt=datetime.fromisoformat(item["expiresAt"]) if item.get("expiresAt") else None
        )

    async def store(self, record: EpisodicMemoryRecord) -> str:
        table = self._getTable()

        try:
            item = self._toItem(record)
            table.put_item(Item=item)
            logger.info("episodic_memory_stored", recordId=record.id, tenantId=record.tenantId)
            return record.id

        except Exception as e:
            logger.error("episodic_store_error", error=str(e), recordId=record.id)
            raise MemoryError(f"Failed to store episodic memory: {str(e)}", "episodic")

    async def retrieve(
        self,
        tenantContext: TenantContext,
        query: str = None,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[EpisodicMemoryRecord]:
        table = self._getTable()

        try:
            pk = f"TENANT#{tenantContext.tenantId}#USER#{tenantContext.userId}"
            keyCondition = Key("pk").eq(pk)

            if filters and filters.get("sessionId"):
                skPrefix = f"SESSION#{filters['sessionId']}#"
                keyCondition = keyCondition & Key("sk").begins_with(skPrefix)

            queryParams = {
                "KeyConditionExpression": keyCondition,
                "Limit": limit,
                "ScanIndexForward": False
            }

            if filters:
                filterExpression = None

                if filters.get("agentId"):
                    filterExpression = Attr("agentId").eq(filters["agentId"])

                if filters.get("tags"):
                    tagFilter = Attr("tags").contains(filters["tags"][0])
                    for tag in filters["tags"][1:]:
                        tagFilter = tagFilter | Attr("tags").contains(tag)
                    filterExpression = filterExpression & tagFilter if filterExpression else tagFilter

                if filters.get("minImportance"):
                    importanceFilter = Attr("importance").gte(Decimal(str(filters["minImportance"])))
                    filterExpression = filterExpression & importanceFilter if filterExpression else importanceFilter

                if filterExpression:
                    queryParams["FilterExpression"] = filterExpression

            response = table.query(**queryParams)
            items = response.get("Items", [])

            return [self._fromItem(item) for item in items]

        except Exception as e:
            logger.error("episodic_retrieve_error", error=str(e), tenantId=tenantContext.tenantId)
            return []

    async def retrieveBySession(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        limit: int = 50
    ) -> List[EpisodicMemoryRecord]:
        return await self.retrieve(
            tenantContext,
            limit=limit,
            filters={"sessionId": sessionId}
        )

    async def retrieveRecent(
        self,
        tenantContext: TenantContext,
        hours: int = 24,
        limit: int = 20
    ) -> List[EpisodicMemoryRecord]:
        memories = await self.retrieve(tenantContext, limit=limit)
        cutoffTime = datetime.utcnow() - timedelta(hours=hours)

        return [m for m in memories if m.createdAt >= cutoffTime]

    async def delete(self, recordId: str, tenantContext: TenantContext) -> bool:
        table = self._getTable()

        try:
            pk = f"TENANT#{tenantContext.tenantId}#USER#{tenantContext.userId}"

            response = table.query(
                KeyConditionExpression=Key("pk").eq(pk),
                FilterExpression=Attr("id").eq(recordId),
                Limit=1
            )

            items = response.get("Items", [])
            if not items:
                return False

            item = items[0]
            table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            logger.info("episodic_memory_deleted", recordId=recordId)
            return True

        except Exception as e:
            logger.error("episodic_delete_error", error=str(e), recordId=recordId)
            return False

    async def update(self, recordId: str, record: EpisodicMemoryRecord, tenantContext: TenantContext) -> bool:
        await self.delete(recordId, tenantContext)
        await self.store(record)
        return True

    async def cleanup(self, tenantContext: TenantContext, olderThanDays: int) -> int:
        cutoffTime = datetime.utcnow() - timedelta(days=olderThanDays)
        memories = await self.retrieve(tenantContext, limit=100)

        deletedCount = 0
        for memory in memories:
            if memory.createdAt < cutoffTime and memory.importance < 0.7:
                if await self.delete(memory.id, tenantContext):
                    deletedCount += 1

        return deletedCount


dynamodbEpisodicMemory = DynamoDBEpisodicMemory()
