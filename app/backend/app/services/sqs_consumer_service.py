"""robot-events(SQS) <- success_load1 / fail_load1 메시지 소비.
PRD: assets/docs/prd-work-request-sqs.md 5장.

- {"work_id":1,"type":"success_load1"}: 베드 집기 성공. board_stock을 비우고 주문을
  LOADING으로 바꾼 뒤, 그 시점에 비어있는 프린터를 찾아 배치 명령(sd_pos_id)을
  robot-commands에 보낸다.
- {"work_id":1,"type":"fail_load1"}: 베드 집기 실패. 로봇/주문 상태는 바꾸지 않고
  웹에 알럿만 띄워서 사람이 적재대를 확인하고 재시도("확인")하게 한다.

robot-events의 다른 이벤트(UNLOAD_COMPLETED/REJECTED 등 주문 상태를 더 진행시키는
것)는 범위 밖이라 여기서는 무시한다."""

import asyncio
import json
import logging
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.events import broadcast_to_web
from app.services.work_request_service import WorkRequestService

logger = logging.getLogger(__name__)

_LOAD_SUCCESS_TYPE = "success_load1"
_LOAD_PICK_FAILED_TYPE = "fail_load1"
_ERROR_BACKOFF_SEC = 3.0


async def _broadcast_sqs_event(event_type: str, data: dict) -> None:
    async with AsyncSessionLocal() as session:
        await broadcast_to_web(session, event_type, data)
        await session.commit()


@lru_cache(maxsize=1)
def _client():
    return boto3.client("sqs", region_name=settings.aws_region)


class SqsConsumerService:
    @staticmethod
    async def robot_events_loop() -> None:
        """event_queue_url이 설정되지 않으면 바로 종료한다 (로컬 개발 등에서 안전한
        기본값). 큐가 설정됐을 때만 long polling으로 계속 수신한다."""
        if not settings.event_queue_url:
            logger.info("event_queue_url 미설정 — robot-events 컨슈머를 시작하지 않습니다.")
            return

        client = _client()
        while True:
            try:
                response = await asyncio.to_thread(
                    client.receive_message,
                    QueueUrl=settings.event_queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=settings.sqs_poll_wait_sec,
                )
            except asyncio.CancelledError:
                raise
            except (BotoCoreError, ClientError) as exc:
                logger.error("robot-events 수신 실패: %s", exc)
                await asyncio.sleep(_ERROR_BACKOFF_SEC)
                continue

            for message in response.get("Messages", []):
                await SqsConsumerService._handle_message(client, message)

    @staticmethod
    async def _handle_message(client, message: dict) -> None:
        try:
            body = json.loads(message["Body"])
        except (json.JSONDecodeError, KeyError):
            logger.error("robot-events 메시지 파싱 실패: %s", message.get("Body"))
            await _broadcast_sqs_event(
                "sqs.event_parse_error", {"raw_body": message.get("Body"), "message_id": message.get("MessageId")}
            )
            await SqsConsumerService._delete(client, message)
            return

        await _broadcast_sqs_event(
            "sqs.event_received", {"body": body, "message_id": message.get("MessageId"), "queue": "robot-events"}
        )

        if body.get("type") == _LOAD_SUCCESS_TYPE and "work_id" in body:
            try:
                await WorkRequestService.handle_load_success(int(body["work_id"]))
            except (TypeError, ValueError):
                logger.error("success_load1 work_id가 올바르지 않습니다: %s", body)
            except Exception:
                # 예상 못한 오류(DB 등)는 메시지를 지우지 않고 가시성 타임아웃이 지난 뒤
                # 재시도되게 둔다. 알 수 없는 work_id/중복 수신은 여기서 예외가 나지
                # 않으므로(handle_load_success가 조용히 무시) 영향 없다.
                logger.exception("success_load1 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("type") == _LOAD_PICK_FAILED_TYPE and "work_id" in body:
            try:
                await WorkRequestService.handle_load_pick_failed(int(body["work_id"]))
            except (TypeError, ValueError):
                logger.error("fail_load1 work_id가 올바르지 않습니다: %s", body)
            except Exception:
                logger.exception("fail_load1 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return

        await SqsConsumerService._delete(client, message)

    @staticmethod
    async def _delete(client, message: dict) -> None:
        try:
            await asyncio.to_thread(
                client.delete_message,
                QueueUrl=settings.event_queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error("robot-events 메시지 삭제 실패: %s", exc)
