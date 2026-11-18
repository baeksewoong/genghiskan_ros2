"""SQS 모니터링 페이지용 큐 상태 조회. ReceiveMessage는 쓰지 않는다 — 큐를 직접
Peek하면 VisibilityTimeout 동안 실제 컨슈머(ROS2 쪽)가 못 받아가게 될 수 있어서,
GetQueueAttributes로 깊이(개수)만 조회한다."""

import asyncio
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.repositories.event_log_repository import EventLogRepository

_ATTRIBUTE_NAMES = [
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
    "ApproximateNumberOfMessagesDelayed",
]


@lru_cache(maxsize=1)
def _client():
    return boto3.client("sqs", region_name=settings.aws_region)


async def _queue_status(name: str, queue_url: str) -> dict:
    if not queue_url:
        return {"name": name, "configured": False, "queue_url": None}

    try:
        response = await asyncio.to_thread(
            _client().get_queue_attributes, QueueUrl=queue_url, AttributeNames=_ATTRIBUTE_NAMES
        )
        attrs = response.get("Attributes", {})
        return {
            "name": name,
            "configured": True,
            "queue_url": queue_url,
            "visible": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
            "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
        }
    except (BotoCoreError, ClientError) as exc:
        return {"name": name, "configured": True, "queue_url": queue_url, "error": str(exc)}


class SqsMonitorService:
    @staticmethod
    async def status() -> dict:
        command_status, event_status = await asyncio.gather(
            _queue_status("robot-commands", settings.command_queue_url),
            _queue_status("robot-events", settings.event_queue_url),
        )
        return {"command_queue": command_status, "event_queue": event_status}

    @staticmethod
    async def history(limit: int = 200) -> list[dict]:
        """event_logs에 이미 기록돼있는 sqs.* 이벤트를 최신순으로 돌려준다 — 모니터링
        페이지를 새로 열었을 때도 그 전에 오간 메시지를 볼 수 있게 한다."""
        async with AsyncSessionLocal() as session:
            rows = await EventLogRepository.list_by_type_prefix(session, "sqs.", limit)
        return [row.payload for row in rows]
