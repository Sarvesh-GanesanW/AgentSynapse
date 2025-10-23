"""
ETL log inspector tool that fetches the latest CloudWatch Log events for a pipeline.

Required toolInput fields:
    - logGroup (str): CloudWatch Logs group name.
    - query (str): Filter pattern, defaults to empty (match all).

Optional toolInput:
    - limit (int): Number of log events to return (default 50).
    - startMinutesAgo (int): Time window to look back (default 60 minutes).

AWS permissions:
    - logs:FilterLogEvents on the target log group.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config.settings import settings


async def execute(toolInput: dict, context: dict) -> dict:
    logGroup = toolInput.get("logGroup")
    if not logGroup:
        return {
            "success": False,
            "error": "Missing required field 'logGroup'"
        }

    filterPattern = toolInput.get("query", "")
    limit = int(toolInput.get("limit", 50))
    startMinutesAgo = int(toolInput.get("startMinutesAgo", 60))

    startTime = datetime.now(timezone.utc) - timedelta(minutes=startMinutesAgo)
    startMillis = int(startTime.timestamp() * 1000)

    loop = asyncio.get_running_loop()

    def _fetchEvents():
        client = boto3.client(
            "logs",
            region_name=settings.aws.region,
            aws_access_key_id=settings.aws.accessKeyId,
            aws_secret_access_key=settings.aws.secretAccessKey
        )

        try:
            response = client.filter_log_events(
                logGroupName=logGroup,
                startTime=startMillis,
                filterPattern=filterPattern,
                limit=limit
            )
        except (ClientError, BotoCoreError) as exc:
            return {"success": False, "error": str(exc)}

        events = [
            {
                "timestamp": event["timestamp"],
                "message": event["message"],
                "ingestionTime": event.get("ingestionTime")
            }
            for event in response.get("events", [])
        ]

        return {
            "success": True,
            "events": events,
            "matchedEvents": len(events),
            "nextToken": response.get("nextToken")
        }

    return await loop.run_in_executor(None, _fetchEvents)
