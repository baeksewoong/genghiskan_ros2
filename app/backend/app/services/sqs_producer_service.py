"""서버 → robot-commands(SQS) 메시지 발행. PRD: assets/docs/prd-work-request-sqs.md 7장,
assets/docs/prd-teaching-pendant.md 7장(JOG/GRIPPER).

LOAD는 두 단계로 나뉜다 — dispatch 시점엔 집을 위치(start_pos_id)만 보내고, 로봇이
success_load1(베드 집기 성공)을 보고하면 그때 비어있는 프린터를 찾아 목적지
(sd_pos_id)를 담은 배치 명령을 따로 보낸다. 같은 work_id라도 두 명령은 서로 다른
MessageDeduplicationId를 써야 FIFO 큐가 서로를 중복으로 보고 하나를 버리지 않는다.

JOG/GRIPPER(티칭 팬던트)는 LOAD/UNLOAD와 MessageGroupId를 분리한다("jog") — 조그
세션 중에는 LOAD/UNLOAD가 아예 발행되지 않는 게 설계 전제(PRD 3장)라 정상
상황에서는 그룹 경합이 생기지 않지만, 혹시라도 겹치는 경우에도 서로의 FIFO
순서에 영향을 주지 않게 분리해 둔다.

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
# 티칭 팬던트(조그/그리퍼) 전용 그룹 — LOAD/UNLOAD와 분리한다 (PRD:
# assets/docs/prd-teaching-pendant.md 7장).
_JOG_MESSAGE_GROUP_ID = "jog"
# UNLOAD2 수령대 위치 — 수령대는 1번/2번 두 곳.
_RECEIVE_POS_IDS = frozenset({1, 2})


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
    async def produce_load_command(work_id: int, start_pos_id: int, retry_token: str | None = None) -> bool:
        """robot-commands에 LOAD(집기) 명령을 보낸다. 이 시점엔 목적지 프린터를
        모른다 — success_load1 수신 후 produce_place_command로 따로 보낸다.
        재시도일 때는 retry_token을 넘겨야 FIFO 중복 제거(5분)에 걸려 버려지지 않는다."""
        return await SqsProducerService._send(
            work_id,
            {"work_id": work_id, "start_pos_id": start_pos_id},
            dedup_prefix="load",
            retry_token=retry_token,
        )

    @staticmethod
    async def produce_place_command(work_id: int, sd_pos_id: int) -> bool:
        """success_load1(베드 집기 성공) 수신 후, 그 시점에 비어있는 프린터를 목적지로
        하는 배치 명령을 robot-commands에 보낸다."""
        return await SqsProducerService._send(
            work_id,
            {"work_id": work_id, "sd_pos_id": sd_pos_id, "type": "load2"},
            dedup_prefix="place",
        )

    @staticmethod
    async def produce_unload_command(work_id: int, sd_pos_id: int, retry_token: str | None = None) -> bool:
        """출력 타이머 완료(PRINT_DONE) 시, 완성품이 놓인 프린터 위치를 목적지로
        하는 수령(UNLOAD) 명령을 robot-commands에 보낸다. 재시도일 때는 retry_token을
        넘긴다(produce_load_command 참고)."""
        return await SqsProducerService._send(
            work_id,
            {"work_id": work_id, "sd_pos_id": sd_pos_id, "type": "unload1"},
            dedup_prefix="unload",
            retry_token=retry_token,
        )

    @staticmethod
    async def produce_unload2_command(work_id: int, receive_pos_id: int, retry_token: str | None = None) -> bool:
        """success_unload1(프린터에서 완성품 집기 성공) 이후, 완성품을 내려놓을
        수령대 위치(receive_pos_id: 1 또는 2)를 담은 UNLOAD2 명령을 robot-commands에
        보낸다. 같은 work_id의 unload1과 겹치지 않도록 dedup prefix를 분리한다.
        수동 발행(POST /api/sqs/commands/unload2)처럼 같은 work_id로 여러 번 보낼
        때는 retry_token을 넘겨야 FIFO 중복 제거(5분)에 걸려 버려지지 않는다."""
        if receive_pos_id not in _RECEIVE_POS_IDS:
            raise ValueError(f"receive_pos_id는 {sorted(_RECEIVE_POS_IDS)} 중 하나여야 합니다: {receive_pos_id}")
        return await SqsProducerService._send(
            work_id,
            {"type": "unload2", "work_id": work_id, "receive_pos_id": receive_pos_id},
            dedup_prefix="unload2",
            retry_token=retry_token,
        )

    @staticmethod
    async def produce_jog_command(
        jog_id: str,
        space: str,
        axis: str,
        direction: int,
        step_size: float,
        ref_frame: str | None = None,
    ) -> bool:
        """robot-commands에 JOG(조그 1스텝) 명령을 보낸다 (PRD:
        assets/docs/prd-teaching-pendant.md 7장). ref_frame은 space=TASK일 때만
        body에 포함한다(JOINT는 기준 좌표계 개념이 없음)."""
        body: dict = {
            "type": "JOG",
            "jog_id": jog_id,
            "space": space,
            "axis": axis,
            "direction": direction,
            "step_size": step_size,
        }
        if ref_frame is not None:
            body["ref_frame"] = ref_frame
        return await SqsProducerService._send_raw(
            message_group_id=_JOG_MESSAGE_GROUP_ID,
            dedup_id=f"jog-{jog_id}",
            body=body,
            log_extra={"jog_id": jog_id},
        )

    @staticmethod
    async def produce_gripper_command(gripper_cmd_id: str, action: str) -> bool:
        """robot-commands에 GRIPPER(개폐) 명령을 보낸다 (PRD:
        assets/docs/prd-teaching-pendant.md 7장). 조그와 같은 MessageGroupId("jog")를
        써서, 한 조그 세션 안에서 조그/그리퍼가 항상 순서대로 하나씩만 실행된다."""
        body = {"type": "GRIPPER", "gripper_cmd_id": gripper_cmd_id, "action": action}
        return await SqsProducerService._send_raw(
            message_group_id=_JOG_MESSAGE_GROUP_ID,
            dedup_id=f"grip-{gripper_cmd_id}",
            body=body,
            log_extra={"gripper_cmd_id": gripper_cmd_id},
        )

    @staticmethod
    async def _send(work_id: int, body: dict, dedup_prefix: str, retry_token: str | None = None) -> bool:
        """LOAD/UNLOAD(work_id 기반) 전용 얇은 래퍼. 성공하면 True, 큐 미설정이거나
        전송에 실패하면 False를 반환한다 (호출 측이 트랜잭션을 롤백한다).
        retry_token이 있으면 dedup id 뒤에 붙여, 같은 work_id의 재전송이 첫 전송의
        중복으로 취급돼 버려지지 않게 한다."""
        dedup_id = f"{dedup_prefix}-{work_id}" + (f"-{retry_token}" if retry_token else "")
        return await SqsProducerService._send_raw(
            message_group_id=_LOAD_MESSAGE_GROUP_ID,
            dedup_id=dedup_id,
            body=body,
            log_extra={"work_id": work_id},
        )

    @staticmethod
    async def _send_raw(message_group_id: str, dedup_id: str, body: dict, log_extra: dict) -> bool:
        """실제 SQS send_message 호출. log_extra는 sqs.command_* 브로드캐스트에
        식별자(work_id 또는 jog_id/gripper_cmd_id)를 실어주기 위한 것 — 호출하는
        쪽의 의미에 따라 키가 달라진다."""
        if not settings.command_queue_url:
            await _broadcast_sqs_event(
                "sqs.command_skipped", {**log_extra, "reason": "COMMAND_QUEUE_URL 미설정"}
            )
            return False

        params: dict = {
            "QueueUrl": settings.command_queue_url,
            "MessageBody": json.dumps(body, ensure_ascii=False),
        }
        if settings.command_queue_url.endswith(".fifo"):
            params["MessageGroupId"] = message_group_id
            params["MessageDeduplicationId"] = dedup_id

        try:
            response = await asyncio.to_thread(_client().send_message, **params)
            await _broadcast_sqs_event(
                "sqs.command_sent",
                {**log_extra, "body": body, "message_id": response.get("MessageId"), "queue": "robot-commands"},
            )
            return True
        except (BotoCoreError, ClientError) as exc:
            logger.error("robot-commands produce 실패 (%s): %s", log_extra, exc)
            await _broadcast_sqs_event(
                "sqs.command_failed", {**log_extra, "body": body, "error": str(exc)}
            )
            return False
