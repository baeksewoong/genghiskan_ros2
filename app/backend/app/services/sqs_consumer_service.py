"""robot-events(SQS) <- success_load1 / success_load2 / fail_load1 /
success_unload1 / success_unload2 / fail_unload1 /
jog_complete / jog_failed / gripper_complete / gripper_failed 메시지 소비.
PRD: assets/docs/prd-work-request-sqs.md 5장, assets/docs/prd-teaching-pendant.md 6/7장.

- {"work_id":1,"type":"success_load1"}: 베드 집기 성공. board_stock을 비우고 주문을
  LOADING으로 바꾼 뒤, 그 시점에 비어있는 프린터를 찾아 배치 명령(sd_pos_id)을
  robot-commands에 보낸다.
- {"work_id":1,"type":"success_load2"}: 프린터 배치 성공. 주문을 LOADING→PRINTING,
  프린터를 RESERVED→PRINTING(타이머 시작)으로 바꾼다("작업중" 표시).
- {"work_id":1,"type":"fail_load1"}: 베드 집기 실패. 로봇/주문 상태는 바꾸지 않고
  웹에 알럿만 띄워서 사람이 적재대를 확인하고 재시도("확인")하게 한다.
- {"work_id":1,"type":"success_unload1"}: 프린터에서 완성품 집기 성공. 비어있는
  수령대(1번 우선, 차 있으면 2번)를 골라 receive_pos_id로 unload2 명령을 보낸다.
- {"work_id":1,"type":"success_unload2"}: 수령대 내려놓기 성공. 주문을
  READY_FOR_PICKUP으로 바꾼다(수령하기 전까지 그 수령대는 점유).
- {"work_id":1,"type":"fail_unload1"}: 완성품 집기 실패. 상태는 그대로 두고 웹에
  "작업대에 베드를 확인하세요!" 알럿만 띄운다.
- {"jog_id":"...","status":"jog_complete"/"jog_failed", ...}: 티칭 팬던트 조그 1스텝
  완료/실패. work_id 계열과 필드명이 달라(status가 아니라 type이 아님) 서로
  겹치지 않는다 — TeachingPendantService의 런타임 조그 세션 상태를 갱신한다.
- {"gripper_cmd_id":"...","status":"gripper_complete"/"gripper_failed", ...}: 티칭
  팬던트 그리퍼 개폐 완료/실패. 위와 동일한 경로.

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
from app.services.teaching_pendant_service import TeachingPendantService
from app.services.work_request_service import WorkRequestService

logger = logging.getLogger(__name__)

_LOAD_SUCCESS_TYPE = "success_load1"
_PLACE_SUCCESS_TYPE = "success_load2"
_LOAD_PICK_FAILED_TYPE = "fail_load1"
_UNLOAD1_SUCCESS_TYPE = "success_unload1"
_UNLOAD1_FAILED_TYPE = "fail_unload1"
_UNLOAD2_SUCCESS_TYPE = "success_unload2"
_ERROR_BACKOFF_SEC = 3.0

# 티칭 팬던트(조그/그리퍼) 이벤트 — PRD: assets/docs/prd-teaching-pendant.md 7장.
# status 필드로 구분한다(LOAD 계열은 type 필드를 쓴다).
_JOG_COMPLETE_STATUS = "jog_complete"
_JOG_FAILED_STATUS = "jog_failed"
_GRIPPER_COMPLETE_STATUS = "gripper_complete"
_GRIPPER_FAILED_STATUS = "gripper_failed"


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
        elif body.get("type") == _PLACE_SUCCESS_TYPE and "work_id" in body:
            try:
                await WorkRequestService.handle_place_success(int(body["work_id"]))
            except (TypeError, ValueError):
                logger.error("success_load2 work_id가 올바르지 않습니다: %s", body)
            except Exception:
                logger.exception("success_load2 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("type") == _LOAD_PICK_FAILED_TYPE and "work_id" in body:
            try:
                await WorkRequestService.handle_load_pick_failed(int(body["work_id"]))
            except (TypeError, ValueError):
                logger.error("fail_load1 work_id가 올바르지 않습니다: %s", body)
            except Exception:
                logger.exception("fail_load1 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("type") == _UNLOAD1_SUCCESS_TYPE and "work_id" in body:
            try:
                await WorkRequestService.handle_unload1_success(int(body["work_id"]))
            except (TypeError, ValueError):
                logger.error("success_unload1 work_id가 올바르지 않습니다: %s", body)
            except Exception:
                logger.exception("success_unload1 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("type") == _UNLOAD2_SUCCESS_TYPE and "work_id" in body:
            try:
                await WorkRequestService.handle_unload2_success(int(body["work_id"]))
            except (TypeError, ValueError):
                logger.error("success_unload2 work_id가 올바르지 않습니다: %s", body)
            except Exception:
                logger.exception("success_unload2 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("type") == _UNLOAD1_FAILED_TYPE and "work_id" in body:
            try:
                await WorkRequestService.handle_unload1_failed(int(body["work_id"]))
            except (TypeError, ValueError):
                logger.error("fail_unload1 work_id가 올바르지 않습니다: %s", body)
            except Exception:
                logger.exception("fail_unload1 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("status") == _JOG_COMPLETE_STATUS and "jog_id" in body:
            try:
                await TeachingPendantService.handle_jog_complete(str(body["jog_id"]), body.get("posx"))
            except Exception:
                logger.exception("jog_complete 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("status") == _JOG_FAILED_STATUS and "jog_id" in body:
            try:
                await TeachingPendantService.handle_jog_failed(str(body["jog_id"]), body.get("error_code"))
            except Exception:
                logger.exception("jog_failed 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("status") == _GRIPPER_COMPLETE_STATUS and "gripper_cmd_id" in body:
            try:
                await TeachingPendantService.handle_gripper_complete(str(body["gripper_cmd_id"]), body.get("state"))
            except Exception:
                logger.exception("gripper_complete 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
                return
        elif body.get("status") == _GRIPPER_FAILED_STATUS and "gripper_cmd_id" in body:
            try:
                await TeachingPendantService.handle_gripper_failed(
                    str(body["gripper_cmd_id"]), body.get("error_code")
                )
            except Exception:
                logger.exception("gripper_failed 처리 실패, 재시도를 위해 메시지를 남겨둡니다: %s", body)
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
