"""서버 → robot-commands(SQS) 메시지 발행. PRD: assets/docs/prd-work-request-sqs.md 7장.

LOAD는 두 단계로 나뉜다 — dispatch 시점엔 집을 위치(start_pos_id)만 보내고, 로봇이
success_load1(베드 집기 성공)을 보고하면 그때 비어있는 프린터를 찾아 목적지
(sd_pos_id)를 담은 배치 명령을 따로 보낸다. 같은 work_id라도 두 명령은 서로 다른
MessageDeduplicationId를 써야 FIFO 큐가 서로를 중복으로 보고 하나를 버리지 않는다.

boto3는 동기(blocking) 클라이언트이므로 asyncio 이벤트 루프를 막지 않도록
asyncio.to_thread로 감싸서 호출한다."""

import asyncio
import json
import logging
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.events import broadcast_to_web

logger = logging.getLogger(__name__)

_LOAD_MESSAGE_GROUP_ID = "load"


@lru_cache(maxsize=1)
def _client():
    return boto3.client("sqs", region_name=settings.aws_region)


async def _broadcast_sqs_event(event_type: str, data: dict) -> None:
    # SQS 모니터링 페이지용 로그. 호출 측의 DB 트랜잭션과 분리된 세션을 써서,
    # 호출 측이 롤백하더라도(SqsProduceError 등) 이 로그는 남는다.
    async with AsyncSessionLocal() as session:
        await broadcast_to_web(session, event_type, data)
        await session.commit()


class SqsProducerService:
    @staticmethod
    async def produce_load_command(work_id: int, start_pos_id: int) -> bool:
        """robot-commands에 LOAD(집기) 명령을 보낸다. 이 시점엔 목적지 프린터를
        모른다 — success_load1 수신 후 produce_place_command로 따로 보낸다."""
        return await SqsProducerService._send(
            work_id, {"work_id": work_id, "start_pos_id": start_pos_id}, dedup_prefix="load"
        )

    @staticmethod
    async def produce_place_command(work_id: int, sd_pos_id: int) -> bool:
        """success_load1(베드 집기 성공) 수신 후, 그 시점에 비어있는 프린터를 목적지로
        하는 배치 명령을 robot-commands에 보낸다."""
        return await SqsProducerService._send(
            work_id, {"work_id": work_id, "sd_pos_id": sd_pos_id}, dedup_prefix="place"
        )

    @staticmethod
    async def _send(work_id: int, body: dict, dedup_prefix: str) -> bool:
        """성공하면 True, 큐 미설정이거나 전송에 실패하면 False를 반환한다
        (호출 측이 트랜잭션을 롤백한다)."""
        if not settings.command_queue_url:
            await _broadcast_sqs_event(
                "sqs.command_skipped", {"work_id": work_id, "reason": "COMMAND_QUEUE_URL 미설정"}
            )
            return False

        params: dict = {
            "QueueUrl": settings.command_queue_url,
            "MessageBody": json.dumps(body, ensure_ascii=False),
        }
        if settings.command_queue_url.endswith(".fifo"):
            params["MessageGroupId"] = _LOAD_MESSAGE_GROUP_ID
            params["MessageDeduplicationId"] = f"{dedup_prefix}-{work_id}"

        try:
            response = await asyncio.to_thread(_client().send_message, **params)
            await _broadcast_sqs_event(
                "sqs.command_sent",
                {"work_id": work_id, "body": body, "message_id": response.get("MessageId"), "queue": "robot-commands"},
            )
            return True
        except (BotoCoreError, ClientError) as exc:
            logger.error("robot-commands produce 실패 (work_id=%s): %s", work_id, exc)
            await _broadcast_sqs_event(
                "sqs.command_failed", {"work_id": work_id, "body": body, "error": str(exc)}
            )
            return False
