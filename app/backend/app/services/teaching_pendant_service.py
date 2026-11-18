"""티칭 팬던트(실물 로봇 조그 제어) 세션/명령 처리.
PRD: assets/docs/prd-teaching-pendant.md.

조그 세션은 DB에 영속화하지 않고 서버 런타임 상태(app.core.runtime.runtime.teaching_pendant)
로만 관리한다 (PRD 5장) — 서버가 재시작되면 항상 비활성 상태로 시작한다.

작업요청(WorkRequestService, 실물 로봇 SQS 경로)과의 상호 배제는 PRD 3장을 그대로
따른다:

  (A) 조그 세션 활성화·조그 요청·그리퍼 요청마다, 실물 로봇 경로에 진행 중인
      robot_tasks가 있는지 RobotTaskRepository.get_active_real_robot_task_locked로
      확인한다. 있으면 거부한다.
  (B) WorkRequestService.create()는 TeachingPendantService.is_session_active()로
      조그 세션이 활성인지 확인해, 활성이면 LOAD를 보내지 않고 주문을 WAITING으로
      남긴다 (이 모듈이 아니라 work_request_service.py에서 호출한다).

PRD 3장 끝의 메모대로, 이 두 체크는 완전한 레이스 방지를 보장하지 않는다 — 조그
세션 상태가 DB가 아니라 런타임 메모리에 있어서 작업요청 경로의 SELECT ... FOR UPDATE
잠금과 조그 세션의 asyncio.Lock이 서로 다른 종류의 잠금이기 때문이다. 낮은 빈도의
엣지 케이스로 남겨둔다(PRD 10장)."""

import asyncio
import logging
import time
import uuid

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.events import broadcast_to_web
from app.core.runtime import runtime
from app.enums import GripperAction, JogSpace
from app.repositories.robot_task_repository import RobotTaskRepository
from app.services.sqs_producer_service import SqsProducerService

logger = logging.getLogger(__name__)

# PRD 9장 — 과도한 1스텝 이동을 막기 위한 상한. ROS 2 쪽 실측 후 조정 가능(10장 미결).
_MAX_LINEAR_STEP_MM = 20.0
_MAX_ANGULAR_STEP_DEG = 15.0  # TASK 회전(Rx/Ry/Rz)과 JOINT 공용 상한.
_TASK_LINEAR_AXES = {"X", "Y", "Z"}
_TASK_ANGULAR_AXES = {"RX", "RY", "RZ"}
_JOINT_AXES = {f"J{i}" for i in range(1, 7)}

# PRD TP-11 — 완료/실패 응답이 이 시간 안에 오지 않으면 타임아웃 처리한다("예: 10초").
_JOG_TIMEOUT_SEC = 10.0


class RobotBusyError(Exception):
    """실물 로봇 작업요청 경로에 진행 중인 robot_tasks가 있어 조그 세션
    활성화/조그/그리퍼 요청을 거부함 (PRD 3장 A)."""


class SessionInactiveError(Exception):
    """조그 세션이 비활성 상태에서 조그/그리퍼/정지 요청이 들어왔을 때 (PRD 6장 — 409)."""


class StepPendingError(Exception):
    """이전 조그/그리퍼 명령이 아직 완료/실패 응답을 받지 못한 상태에서 새 요청이
    들어왔을 때 (PRD 8.2 스텝 상호 배제 — 409)."""


class InvalidJogRequestError(Exception):
    """space/axis/ref_frame 조합이 잘못됐거나 스텝 크기가 PRD 9장 상한을 초과했을 때
    (400으로 매핑)."""

    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class JogProduceError(Exception):
    """robot-commands에 JOG 명령 전송 실패 (502로 매핑)."""

    def __init__(self, jog_id: str):
        self.jog_id = jog_id
        super().__init__(f"SQS JOG produce failed for jog_id {jog_id}")


class GripperProduceError(Exception):
    """robot-commands에 GRIPPER 명령 전송 실패 (502로 매핑)."""

    def __init__(self, gripper_cmd_id: str):
        self.gripper_cmd_id = gripper_cmd_id
        super().__init__(f"SQS GRIPPER produce failed for gripper_cmd_id {gripper_cmd_id}")


class TeachingPendantService:
    # ---- 작업요청 경로(WorkRequestService)가 참조하는 조회 ----

    @staticmethod
    def is_session_active() -> bool:
        """WorkRequestService.create()가 작업요청 상호 배제(PRD 3장 B) 판단에 쓴다."""
        return runtime.teaching_pendant.enabled

    # ---- 세션 활성화/비활성화 (TP-01) ----

    @staticmethod
    async def set_session(enable: bool, owner: str | None = None) -> dict:
        if enable:
            return await TeachingPendantService.enable_session(owner)
        return await TeachingPendantService.disable_session()

    @staticmethod
    async def enable_session(owner: str | None = None) -> dict:
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if session.enabled:
                # 이미 활성 상태 — 재활성화 요청은 현재 상태를 그대로 반환한다
                # (단순 멱등 처리; 소유권 교체는 하지 않는다).
                return {"enabled": True, "current_pose": session.current_pose}

            if await TeachingPendantService._real_robot_task_active():
                raise RobotBusyError()

            session.enabled = True
            session.owner = owner
            session.clear_pending()
            current_pose = session.current_pose

        async with AsyncSessionLocal() as db_session:
            await broadcast_to_web(
                db_session, "teaching_pendant.session_changed", {"enabled": True, "owner": owner}
            )
            await db_session.commit()
        return {"enabled": True, "current_pose": current_pose}

    @staticmethod
    async def disable_session() -> dict:
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            session.enabled = False
            session.owner = None
            session.clear_pending()
            current_pose = session.current_pose

        async with AsyncSessionLocal() as db_session:
            await broadcast_to_web(
                db_session, "teaching_pendant.session_changed", {"enabled": False, "owner": None}
            )
            await db_session.commit()
        return {"enabled": False, "current_pose": current_pose}

    # ---- 조그 (TP-06) ----

    @staticmethod
    async def request_jog(
        space: str, axis: str, direction: int, step_size: float, ref_frame: str | None = None
    ) -> str:
        """방향키 1회 클릭. 세션 비활성/이전 스텝 진행 중이면 409로 거부하고(8.2),
        실물 로봇 작업요청 경로에 진행 중인 작업이 있으면도 거부한다(PRD 3장 A —
        조그 요청마다 다시 확인). 성공하면 jog_id를 반환하고 SQS에 JOG 명령을
        보낸다."""
        TeachingPendantService._validate_jog(space, axis, direction, ref_frame, step_size)

        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if not session.enabled:
                raise SessionInactiveError()
            if session.has_pending():
                raise StepPendingError()
            if await TeachingPendantService._real_robot_task_active():
                raise RobotBusyError()

            jog_id = str(uuid.uuid4())
            session.pending_jog_id = jog_id
            session.pending_since_monotonic = time.monotonic()

        produced = await SqsProducerService.produce_jog_command(
            jog_id=jog_id, space=space, axis=axis, direction=direction, step_size=step_size, ref_frame=ref_frame
        )
        if not produced:
            await TeachingPendantService._clear_pending_if_matches(jog_id=jog_id)
            raise JogProduceError(jog_id)

        return jog_id

    # ---- 그리퍼 (TP-12) ----

    @staticmethod
    async def request_gripper(action: str) -> str:
        if action not in (GripperAction.OPEN.value, GripperAction.CLOSE.value):
            raise InvalidJogRequestError("INVALID_ACTION", f"알 수 없는 그리퍼 action입니다: {action}")

        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if not session.enabled:
                raise SessionInactiveError()
            if session.has_pending():
                raise StepPendingError()
            if await TeachingPendantService._real_robot_task_active():
                raise RobotBusyError()

            gripper_cmd_id = str(uuid.uuid4())
            session.pending_gripper_cmd_id = gripper_cmd_id
            session.pending_since_monotonic = time.monotonic()

        produced = await SqsProducerService.produce_gripper_command(gripper_cmd_id=gripper_cmd_id, action=action)
        if not produced:
            await TeachingPendantService._clear_pending_if_matches(gripper_cmd_id=gripper_cmd_id)
            raise GripperProduceError(gripper_cmd_id)

        return gripper_cmd_id

    # ---- 정지 (TP-09) ----

    @staticmethod
    async def request_stop() -> dict:
        """PRD 8.4 — SQS는 이미 발행된 명령을 취소하는 기본 수단이 없다. 여기서
        보장하는 건 "다음 스텝을 보내지 않도록 막는 것"뿐이다(이미 pending 상태가
        있으면 그대로 두어 다음 요청이 자연히 409로 막힌다 — 8.2 상호 배제와 같은
        메커니즘). ROS 2 쪽에 실제 정지 신호를 보내는 전용 SQS 메시지 타입은 PRD
        7장에 정의돼 있지 않아(10장 미결), 지금은 서버가 보장할 수 있는 범위까지만
        처리하고 그 한계를 응답 메시지로 고지한다."""
        if not runtime.teaching_pendant.enabled:
            raise SessionInactiveError()
        return {
            "ok": True,
            "message": "정지 요청 접수 — 이미 시작된 이동/그리퍼 동작은 완료될 수 있습니다",
        }

    # ---- robot-events 완료/실패 처리 (consumer가 호출) ----

    @staticmethod
    async def handle_jog_complete(jog_id: str, posx: list | None) -> None:
        current_pose: dict | None = None
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if session.pending_jog_id != jog_id:
                return  # 알 수 없는/중복 jog_id — 조용히 무시 (PRD 8장)
            session.pending_jog_id = None
            session.pending_since_monotonic = None
            if posx is not None:
                session.current_pose = {"space": "TASK", "posx": posx}
            current_pose = session.current_pose

        async with AsyncSessionLocal() as db_session:
            await broadcast_to_web(
                db_session, "teaching_pendant.jog_completed", {"jog_id": jog_id, "current_pose": current_pose}
            )
            await db_session.commit()

    @staticmethod
    async def handle_jog_failed(jog_id: str, error_code: str | None) -> None:
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if session.pending_jog_id != jog_id:
                return
            session.pending_jog_id = None
            session.pending_since_monotonic = None

        async with AsyncSessionLocal() as db_session:
            await broadcast_to_web(
                db_session, "teaching_pendant.jog_failed", {"jog_id": jog_id, "error_code": error_code}
            )
            await db_session.commit()

    @staticmethod
    async def handle_gripper_complete(gripper_cmd_id: str, state: str | None) -> None:
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if session.pending_gripper_cmd_id != gripper_cmd_id:
                return
            session.pending_gripper_cmd_id = None
            session.pending_since_monotonic = None
            session.gripper_state = state

        async with AsyncSessionLocal() as db_session:
            await broadcast_to_web(
                db_session,
                "teaching_pendant.gripper_completed",
                {"gripper_cmd_id": gripper_cmd_id, "state": state},
            )
            await db_session.commit()

    @staticmethod
    async def handle_gripper_failed(gripper_cmd_id: str, error_code: str | None) -> None:
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if session.pending_gripper_cmd_id != gripper_cmd_id:
                return
            session.pending_gripper_cmd_id = None
            session.pending_since_monotonic = None

        async with AsyncSessionLocal() as db_session:
            await broadcast_to_web(
                db_session,
                "teaching_pendant.gripper_failed",
                {"gripper_cmd_id": gripper_cmd_id, "error_code": error_code},
            )
            await db_session.commit()

    # ---- 타임아웃(TP-11) ----

    @staticmethod
    async def sweep_timeouts() -> None:
        """pending 조그/그리퍼 명령이 타임아웃(기본 10초) 내 완료/실패 응답을 받지
        못하면 타임아웃 처리한다. PRD 8장: 세션 자체는 비활성화하지 않고 운영자
        판단에 맡긴다 — 로봇이 실제로 아직 움직이고 있을 수 있어서다."""
        now = time.monotonic()
        timed_out_jog_id: str | None = None
        timed_out_gripper_cmd_id: str | None = None
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if (
                session.pending_since_monotonic is not None
                and now - session.pending_since_monotonic >= _JOG_TIMEOUT_SEC
            ):
                timed_out_jog_id = session.pending_jog_id
                timed_out_gripper_cmd_id = session.pending_gripper_cmd_id

        # PRD 6장 — 타임아웃도 jog_failed/gripper_failed와 같은 이벤트 타입을 쓴다.
        if timed_out_jog_id is not None:
            await TeachingPendantService.handle_jog_failed(timed_out_jog_id, "TIMEOUT")
        elif timed_out_gripper_cmd_id is not None:
            await TeachingPendantService.handle_gripper_failed(timed_out_gripper_cmd_id, "TIMEOUT")

    @staticmethod
    async def sweep_loop() -> None:
        while True:
            await asyncio.sleep(settings.timer_sweep_interval_sec)
            try:
                await TeachingPendantService.sweep_timeouts()
            except Exception:
                # 한 사이클의 오류가 스윕 루프 전체를 멈추지 않도록 한다
                # (TimerService.sweep_loop와 같은 관례).
                logger.exception("teaching pendant timeout sweep cycle failed")

    # ---- 내부 헬퍼 ----

    @staticmethod
    async def _real_robot_task_active() -> bool:
        """PRD 3장 A — 실물 로봇 경로(작업요청)에 진행 중인 robot_tasks가 있는지
        확인한다. 조회만 하고 바로 롤백해 잠금을 즉시 해제한다."""
        async with AsyncSessionLocal() as db_session:
            active = await RobotTaskRepository.get_active_real_robot_task_locked(db_session)
            await db_session.rollback()
        return active is not None

    @staticmethod
    async def _clear_pending_if_matches(jog_id: str | None = None, gripper_cmd_id: str | None = None) -> None:
        """SQS produce 실패 시 pending을 롤백한다 — 그 사이 다른 이벤트가 먼저
        pending을 지웠다면(이론상 가능성은 낮지만) 덮어쓰지 않는다."""
        async with runtime.teaching_pendant_lock:
            session = runtime.teaching_pendant
            if jog_id is not None and session.pending_jog_id == jog_id:
                session.pending_jog_id = None
                session.pending_since_monotonic = None
            if gripper_cmd_id is not None and session.pending_gripper_cmd_id == gripper_cmd_id:
                session.pending_gripper_cmd_id = None
                session.pending_since_monotonic = None

    @staticmethod
    def _validate_jog(space: str, axis: str, direction: int, ref_frame: str | None, step_size: float) -> None:
        if direction not in (1, -1):
            raise InvalidJogRequestError("INVALID_DIRECTION", "direction은 1 또는 -1이어야 합니다")

        if space == JogSpace.TASK.value:
            if ref_frame not in ("BASE", "TOOL"):
                raise InvalidJogRequestError(
                    "INVALID_REF_FRAME", "TASK 모드는 ref_frame(BASE 또는 TOOL)이 필요합니다"
                )
            if axis in _TASK_LINEAR_AXES:
                if not (0 < step_size <= _MAX_LINEAR_STEP_MM):
                    raise InvalidJogRequestError(
                        "STEP_SIZE_EXCEEDED", f"선형 스텝은 0 초과 {_MAX_LINEAR_STEP_MM}mm 이하만 허용됩니다"
                    )
            elif axis in _TASK_ANGULAR_AXES:
                if not (0 < step_size <= _MAX_ANGULAR_STEP_DEG):
                    raise InvalidJogRequestError(
                        "STEP_SIZE_EXCEEDED", f"회전 스텝은 0 초과 {_MAX_ANGULAR_STEP_DEG}deg 이하만 허용됩니다"
                    )
            else:
                raise InvalidJogRequestError("INVALID_AXIS", f"TASK 모드에 유효하지 않은 축입니다: {axis}")
        elif space == JogSpace.JOINT.value:
            if axis not in _JOINT_AXES:
                raise InvalidJogRequestError("INVALID_AXIS", f"JOINT 모드에 유효하지 않은 축입니다: {axis}")
            if not (0 < step_size <= _MAX_ANGULAR_STEP_DEG):
                raise InvalidJogRequestError(
                    "STEP_SIZE_EXCEEDED", f"Joint 스텝은 0 초과 {_MAX_ANGULAR_STEP_DEG}deg 이하만 허용됩니다"
                )
        else:
            raise InvalidJogRequestError("INVALID_SPACE", f"알 수 없는 space입니다: {space}")
