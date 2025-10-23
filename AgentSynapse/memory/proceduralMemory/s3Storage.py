import boto3
import json
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import MemoryError
from utils.serialization import DecimalEncoder
from schemas import ProceduralMemoryRecord, TenantContext

logger = getLogger(__name__)


class S3ProceduralMemory:
    def __init__(self):
        self._s3 = None
        self._dynamodb = None
        self._metaTable = None
        self.bucket = settings.s3.bucketProcedural

    def _getS3(self):
        if not self._s3:
            self._s3 = boto3.client(
                "s3",
                region_name=settings.aws.region,
                aws_access_key_id=settings.aws.accessKeyId,
                aws_secret_access_key=settings.aws.secretAccessKey
            )
        return self._s3

    def _getDynamoDB(self):
        if not self._dynamodb:
            resourceArgs = {
                "region_name": settings.aws.region,
                "aws_access_key_id": settings.aws.accessKeyId,
                "aws_secret_access_key": settings.aws.secretAccessKey
            }
            if settings.dynamodb.endpointUrl:
                resourceArgs["endpoint_url"] = settings.dynamodb.endpointUrl

            self._dynamodb = boto3.resource("dynamodb", **resourceArgs)
            self._metaTable = self._dynamodb.Table("aceProceduralMetadata")
        return self._metaTable

    def _buildS3Key(self, tenantId: str, recordId: str) -> str:
        return f"{tenantId}/procedural/{recordId}.json"

    async def store(self, record: ProceduralMemoryRecord) -> str:
        s3 = self._getS3()
        table = self._getDynamoDB()

        s3Key = self._buildS3Key(record.tenantId, record.id)

        workflowData = {
            "id": record.id,
            "name": record.name,
            "description": record.description,
            "workflow": record.workflow,
            "createdAt": record.createdAt.isoformat(),
            "updatedAt": record.updatedAt.isoformat()
        }

        try:
            s3.put_object(
                Bucket=self.bucket,
                Key=s3Key,
                Body=json.dumps(workflowData, cls=DecimalEncoder),
                ContentType="application/json"
            )

            table.put_item(Item={
                "id": record.id,
                "tenantId": record.tenantId,
                "name": record.name,
                "description": record.description,
                "s3Key": s3Key,
                "successCount": record.successCount,
                "failureCount": record.failureCount,
                "avgExecutionTimeMs": record.avgExecutionTimeMs,
                "tags": record.tags,
                "createdAt": record.createdAt.isoformat(),
                "updatedAt": record.updatedAt.isoformat()
            })

            logger.info("procedural_memory_stored", recordId=record.id, s3Key=s3Key)
            return record.id

        except Exception as e:
            logger.error("procedural_store_error", error=str(e), recordId=record.id)
            raise MemoryError(f"Failed to store procedural memory: {str(e)}", "procedural")

    async def retrieve(self, recordId: str, tenantContext: TenantContext) -> Optional[ProceduralMemoryRecord]:
        s3 = self._getS3()
        table = self._getDynamoDB()

        try:
            response = table.get_item(Key={"id": recordId})
            if "Item" not in response:
                return None

            item = response["Item"]

            if item["tenantId"] != tenantContext.tenantId:
                raise MemoryError("Access denied to procedural memory", "procedural")

            s3Response = s3.get_object(Bucket=self.bucket, Key=item["s3Key"])
            workflowData = json.loads(s3Response["Body"].read())

            record = ProceduralMemoryRecord(
                id=item["id"],
                tenantId=item["tenantId"],
                name=item["name"],
                description=item["description"],
                workflow=workflowData["workflow"],
                s3Key=item["s3Key"],
                successCount=item.get("successCount", 0),
                failureCount=item.get("failureCount", 0),
                avgExecutionTimeMs=item.get("avgExecutionTimeMs", 0.0),
                tags=item.get("tags", []),
                createdAt=datetime.fromisoformat(item["createdAt"]),
                updatedAt=datetime.fromisoformat(item["updatedAt"])
            )

            return record

        except Exception as e:
            logger.error("procedural_retrieve_error", error=str(e), recordId=recordId)
            return None

    async def search(
        self,
        tenantContext: TenantContext,
        namePattern: Optional[str] = None,
        tags: Optional[List[str]] = None,
        minSuccessRate: Optional[float] = None,
        limit: int = 20
    ) -> List[ProceduralMemoryRecord]:
        table = self._getDynamoDB()

        try:
            filterExpr = None

            if namePattern:
                filterExpr = Attr("name").contains(namePattern)

            if tags:
                tagFilter = Attr("tags").contains(tags[0])
                for tag in tags[1:]:
                    tagFilter = tagFilter | Attr("tags").contains(tag)
                filterExpr = filterExpr & tagFilter if filterExpr else tagFilter

            if minSuccessRate is not None:
                successFilter = Attr("successCount").gte(Attr("failureCount") * minSuccessRate)
                filterExpr = filterExpr & successFilter if filterExpr else successFilter

            scanParams = {
                "FilterExpression": Attr("tenantId").eq(tenantContext.tenantId),
                "Limit": limit
            }

            if filterExpr:
                scanParams["FilterExpression"] = scanParams["FilterExpression"] & filterExpr

            response = table.scan(**scanParams)
            items = response.get("Items", [])

            records = []
            for item in items:
                record = ProceduralMemoryRecord(
                    id=item["id"],
                    tenantId=item["tenantId"],
                    name=item["name"],
                    description=item["description"],
                    workflow=[],
                    s3Key=item["s3Key"],
                    successCount=item.get("successCount", 0),
                    failureCount=item.get("failureCount", 0),
                    avgExecutionTimeMs=item.get("avgExecutionTimeMs", 0.0),
                    tags=item.get("tags", []),
                    createdAt=datetime.fromisoformat(item["createdAt"]),
                    updatedAt=datetime.fromisoformat(item["updatedAt"])
                )
                records.append(record)

            return records

        except Exception as e:
            logger.error("procedural_search_error", error=str(e))
            return []

    async def updateStats(
        self,
        recordId: str,
        success: bool,
        executionTimeMs: int,
        tenantContext: TenantContext
    ) -> bool:
        table = self._getDynamoDB()

        try:
            if success:
                updateExpr = """
                SET successCount = successCount + :inc,
                    avgExecutionTimeMs = (avgExecutionTimeMs * successCount + :time) / (successCount + :inc),
                    updatedAt = :now
                """
            else:
                updateExpr = "SET failureCount = failureCount + :inc, updatedAt = :now"

            table.update_item(
                Key={"id": recordId},
                UpdateExpression=updateExpr,
                ExpressionAttributeValues={
                    ":inc": 1,
                    ":time": Decimal(str(executionTimeMs)),
                    ":now": datetime.utcnow().isoformat()
                },
                ConditionExpression=Attr("tenantId").eq(tenantContext.tenantId)
            )

            logger.info("procedural_stats_updated", recordId=recordId, success=success)
            return True

        except Exception as e:
            logger.error("procedural_update_stats_error", error=str(e), recordId=recordId)
            return False

    async def delete(self, recordId: str, tenantContext: TenantContext) -> bool:
        s3 = self._getS3()
        table = self._getDynamoDB()

        try:
            response = table.get_item(Key={"id": recordId})
            if "Item" not in response:
                return False

            item = response["Item"]

            if item["tenantId"] != tenantContext.tenantId:
                return False

            s3.delete_object(Bucket=self.bucket, Key=item["s3Key"])
            table.delete_item(Key={"id": recordId})

            logger.info("procedural_memory_deleted", recordId=recordId)
            return True

        except Exception as e:
            logger.error("procedural_delete_error", error=str(e), recordId=recordId)
            return False


s3ProceduralMemory = S3ProceduralMemory()
