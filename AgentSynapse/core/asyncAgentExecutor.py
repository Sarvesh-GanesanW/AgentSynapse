import boto3
import json
import httpx
from typing import Dict, Any, Optional
from datetime import datetime
from uuid import uuid4
from config.settings import settings
from utils.logger import getLogger
from schemas import AgentStatus, TenantContext
from core.agentEngine import agentEngine
from agents.registry.agentRegistry import agentRegistry
from utils.exceptions import AgentNotFound

logger = getLogger(__name__)


class AsyncAgentExecutor:
    def __init__(self):
        self._sqs = None
        self._dynamodb = None
        self._table = None
        self.engine = agentEngine
        self.agentRegistry = agentRegistry

    def _getSQS(self):
        if not self._sqs:
            self._sqs = boto3.client(
                "sqs",
                region_name=settings.aws.region,
                aws_access_key_id=settings.aws.accessKeyId,
                aws_secret_access_key=settings.aws.secretAccessKey
            )
        return self._sqs

    def _getTable(self):
        if not self._table:
            resourceArgs = {
                "region_name": settings.aws.region,
                "aws_access_key_id": settings.aws.accessKeyId,
                "aws_secret_access_key": settings.aws.secretAccessKey
            }
            if settings.dynamodb.endpointUrl:
                resourceArgs["endpoint_url"] = settings.dynamodb.endpointUrl

            dynamodb = boto3.resource("dynamodb", **resourceArgs)
            self._table = dynamodb.Table(settings.dynamodb.tableSessions)
        return self._table

    async def submitAsyncTask(
        self,
        agentId: str,
        userMessage: str,
        sessionId: str,
        tenantContext: TenantContext,
        authToken: Optional[str] = None,
        callbackUrl: Optional[str] = None
    ) -> str:
        sqs = self._getSQS()
        table = self._getTable()

        taskId = str(uuid4())

        message = {
            "taskId": taskId,
            "agentId": agentId,
            "userMessage": userMessage,
            "sessionId": sessionId,
            "tenantContext": {
                "tenantId": tenantContext.tenantId,
                "userId": tenantContext.userId,
                "orgId": tenantContext.orgId,
                "roles": tenantContext.roles,
                "permissions": tenantContext.permissions
            },
            "authToken": authToken,
            "callbackUrl": callbackUrl,
            "submittedAt": datetime.utcnow().isoformat()
        }

        try:
            queueUrl = self._getQueueUrl()

            sqs.send_message(
                QueueUrl=queueUrl,
                MessageBody=json.dumps(message),
                MessageAttributes={
                    "tenantId": {
                        "StringValue": tenantContext.tenantId,
                        "DataType": "String"
                    },
                    "taskId": {
                        "StringValue": taskId,
                        "DataType": "String"
                    }
                }
            )

            table.put_item(Item={
                "pk": f"TENANT#{tenantContext.tenantId}#SESSION#{sessionId}",
                "sk": f"TASK#{taskId}",
                "taskId": taskId,
                "agentId": agentId,
                "status": AgentStatus.IDLE.value,
                "submittedAt": datetime.utcnow().isoformat(),
                "callbackUrl": callbackUrl
            })

            logger.info("async_task_submitted", taskId=taskId, agentId=agentId)
            return taskId

        except Exception as e:
            logger.error("async_task_submission_error", error=str(e))
            raise

    async def processAsyncTask(self, messageBody: Dict[str, Any]) -> Dict[str, Any]:
        taskId = messageBody["taskId"]
        agentId = messageBody["agentId"]
        userMessage = messageBody["userMessage"]
        sessionId = messageBody["sessionId"]
        authToken = messageBody.get("authToken")
        callbackUrl = messageBody.get("callbackUrl")

        tenantContextData = messageBody["tenantContext"]
        tenantContext = TenantContext(
            tenantId=tenantContextData["tenantId"],
            userId=tenantContextData["userId"],
            orgId=tenantContextData.get("orgId"),
            roles=tenantContextData.get("roles", []),
            permissions=tenantContextData.get("permissions", [])
        )

        table = self._getTable()

        try:
            table.update_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}#SESSION#{sessionId}",
                    "sk": f"TASK#{taskId}"
                },
                UpdateExpression="SET #status = :running, startedAt = :now",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":running": AgentStatus.RUNNING.value,
                    ":now": datetime.utcnow().isoformat()
                }
            )

            agent = await self.agentRegistry.get(agentId, tenantContext)

            execution = await self.engine.execute(
                agent,
                userMessage,
                sessionId,
                authToken
            )

            table.update_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}#SESSION#{sessionId}",
                    "sk": f"TASK#{taskId}"
                },
                UpdateExpression="SET #status = :status, completedAt = :now, response = :response, tokensUsed = :tokens",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": execution.status.value,
                    ":now": datetime.utcnow().isoformat(),
                    ":response": execution.agentResponse or "",
                    ":tokens": execution.tokensUsed
                }
            )

            if callbackUrl:
                await self._sendCallback(callbackUrl, taskId, execution)

            logger.info("async_task_completed", taskId=taskId, status=execution.status.value)

            return {
                "taskId": taskId,
                "status": execution.status.value,
                "response": execution.agentResponse,
                "tokensUsed": execution.tokensUsed
            }

        except AgentNotFound as e:
            errorMessage = str(e)
            logger.error("async_task_processing_error", error=errorMessage, taskId=taskId)

            table.update_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}#SESSION#{sessionId}",
                    "sk": f"TASK#{taskId}"
                },
                UpdateExpression="SET #status = :failed, completedAt = :now, errorMessage = :error",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":failed": AgentStatus.FAILED.value,
                    ":now": datetime.utcnow().isoformat(),
                    ":error": errorMessage
                }
            )

            if callbackUrl:
                await self._sendCallback(callbackUrl, taskId, None, error=errorMessage)

            return {
                "taskId": taskId,
                "status": AgentStatus.FAILED.value,
                "error": errorMessage
            }

        except Exception as e:
            logger.error("async_task_processing_error", error=str(e), taskId=taskId)

            table.update_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}#SESSION#{sessionId}",
                    "sk": f"TASK#{taskId}"
                },
                UpdateExpression="SET #status = :failed, completedAt = :now, errorMessage = :error",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":failed": AgentStatus.FAILED.value,
                    ":now": datetime.utcnow().isoformat(),
                    ":error": str(e)
                }
            )

            if callbackUrl:
                await self._sendCallback(callbackUrl, taskId, None, error=str(e))

            return {
                "taskId": taskId,
                "status": AgentStatus.FAILED.value,
                "error": str(e)
            }

    async def getTaskStatus(
        self,
        taskId: str,
        sessionId: str,
        tenantContext: TenantContext
    ) -> Optional[Dict[str, Any]]:
        table = self._getTable()

        try:
            response = table.get_item(
                Key={
                    "pk": f"TENANT#{tenantContext.tenantId}#SESSION#{sessionId}",
                    "sk": f"TASK#{taskId}"
                }
            )

            if "Item" not in response:
                return None

            return response["Item"]

        except Exception as e:
            logger.error("get_task_status_error", error=str(e), taskId=taskId)
            return None

    async def _sendCallback(
        self,
        callbackUrl: str,
        taskId: str,
        execution: Optional[Any] = None,
        error: Optional[str] = None
    ):
        payload = {"taskId": taskId}

        if execution:
            payload.update({
                "status": execution.status.value,
                "response": execution.agentResponse,
                "tokensUsed": execution.tokensUsed
            })
        elif error:
            payload.update({
                "status": AgentStatus.FAILED.value,
                "error": error
            })

        try:
            async with httpx.AsyncClient() as client:
                await client.post(callbackUrl, json=payload, timeout=10.0)
                logger.info("callback_sent", taskId=taskId, callbackUrl=callbackUrl)

        except Exception as e:
            logger.error("callback_send_error", error=str(e), taskId=taskId)

    def _getQueueUrl(self) -> str:
        sqs = self._getSQS()
        response = sqs.get_queue_url(QueueName=settings.asyncAgent.sqsQueue)
        return response["QueueUrl"]


asyncAgentExecutor = AsyncAgentExecutor()
