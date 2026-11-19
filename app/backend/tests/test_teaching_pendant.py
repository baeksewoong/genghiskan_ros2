from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.runtime import runtime
from app.enums import BoardStockStatus, OrderStatus, Shape
from app.models import BoardStock, Order, RobotTask, User
from app.services.sqs_producer_service import SqsProducerService
from app.services.teaching_pendant_service import (
    GripperProduceError,
    InvalidJogRequestError,
    JogProduceError,
    RobotBusyError,
    SessionInactiveError,
    StepPendingError,
    TeachingPendantService,
)
from app.services.work_request_service import WorkRequestService

pytestmark = pytest.mark.asyncio


async def _occupy(slot: int) -> None:
    async with AsyncSessionLocal() as session:
        board = await session.get(BoardStock, slot)
        board.status = BoardStockStatus.OCCUPIED
        board.updated_at = datetime.utcnow()
        await session.commit()


def _fake_produce(result: bool):
    async def _produce(*args, **kwargs) -> bool:
        return result

    return _produce


# ---- 활성화 (TP-01, PRD 3장 A) ----


async def test_enable_rejected_when_real_robot_task_active(monkeypatch):
    """실물 로봇 작업요청 경로에 진행 중인 작업(DISPATCHED, start_pos_id 있음)이
    있으면 조그 세션 활성화를 거부한다."""
    await _occupy(2)
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(True))

    async with AsyncSessionLocal() as session:
        await WorkRequestService.create(session, shape=None)

    with pytest.raises(RobotBusyError):
        await TeachingPendantService.enable_session()

    assert runtime.teaching_pendant.enabled is False


async def test_enable_rejected_when_real_robot_task_active_for_unload(monkeypatch):
    """unload1~unload2 사이(로봇이 완성품을 들고 있는 동안)에도 조그 세션 활성화를
    거부해야 한다 — robot_tasks에 UNLOAD 작업 행이 남아 있어야 가능하다."""
    sent: list[dict] = []

    async def _fake_produce_unload(*, work_id, sd_pos_id):
        sent.append({"work_id": work_id, "sd_pos_id": sd_pos_id})
        return True

    monkeypatch.setattr(SqsProducerService, "produce_unload_command", _fake_produce_unload)

    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        user = User(name="tester", created_at=now)
        session.add(user)
        await session.flush()
        order = Order(
            user_id=user.id,
            shape=Shape.TRIANGLE,
            print_duration_sec=30,
            status=OrderStatus.PRINT_DONE,
            printer_slot=1,
            created_at=now,
            print_completed_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()
        order_id = order.id

    assert await WorkRequestService._try_dispatch_unload1(order_id) is True
    assert sent == [{"work_id": order_id, "sd_pos_id": 1}]

    with pytest.raises(RobotBusyError):
        await TeachingPendantService.enable_session()

    assert runtime.teaching_pendant.enabled is False


async def test_enable_succeeds_when_no_active_real_robot_task():
    result = await TeachingPendantService.enable_session(owner="op1")
    assert result == {"enabled": True, "current_pose": None}
    assert runtime.teaching_pendant.enabled is True
    assert runtime.teaching_pendant.owner == "op1"


async def test_disable_session_clears_state():
    await TeachingPendantService.enable_session()
    result = await TeachingPendantService.disable_session()
    assert result["enabled"] is False
    assert runtime.teaching_pendant.enabled is False
    assert runtime.teaching_pendant.owner is None


# ---- 조그 (TP-06, 8.2 스텝 상호 배제, 9장 스텝 상한) ----


async def test_jog_request_success_and_complete(monkeypatch):
    sent = []

    async def _fake_jog(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(SqsProducerService, "produce_jog_command", _fake_jog)
    await TeachingPendantService.enable_session()

    jog_id = await TeachingPendantService.request_jog(
        space="TASK", axis="X", direction=1, step_size=5, ref_frame="BASE"
    )
    assert sent == [
        {"jog_id": jog_id, "space": "TASK", "axis": "X", "direction": 1, "step_size": 5, "ref_frame": "BASE"}
    ]
    assert runtime.teaching_pendant.pending_jog_id == jog_id

    await TeachingPendantService.handle_jog_complete(jog_id, [1, 2, 3, 0, 0, 0])
    assert runtime.teaching_pendant.pending_jog_id is None
    assert runtime.teaching_pendant.current_pose == {"space": "TASK", "posx": [1, 2, 3, 0, 0, 0]}


async def test_jog_request_rejected_when_session_inactive():
    with pytest.raises(SessionInactiveError):
        await TeachingPendantService.request_jog(space="TASK", axis="X", direction=1, step_size=5, ref_frame="BASE")


async def test_jog_step_size_exceeded_rejected(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_jog_command", _fake_produce(True))
    await TeachingPendantService.enable_session()

    with pytest.raises(InvalidJogRequestError) as exc_info:
        await TeachingPendantService.request_jog(
            space="TASK", axis="X", direction=1, step_size=25, ref_frame="BASE"
        )
    assert exc_info.value.error_code == "STEP_SIZE_EXCEEDED"

    with pytest.raises(InvalidJogRequestError) as exc_info:
        await TeachingPendantService.request_jog(space="JOINT", axis="J1", direction=1, step_size=20)
    assert exc_info.value.error_code == "STEP_SIZE_EXCEEDED"

    # 상한 초과 요청은 pending을 남기지 않아야 다음 정상 요청이 막히지 않는다.
    assert runtime.teaching_pendant.has_pending() is False


async def test_jog_request_rejected_while_pending(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_jog_command", _fake_produce(True))
    await TeachingPendantService.enable_session()

    await TeachingPendantService.request_jog(space="TASK", axis="X", direction=1, step_size=5, ref_frame="BASE")

    with pytest.raises(StepPendingError):
        await TeachingPendantService.request_jog(space="TASK", axis="Y", direction=1, step_size=5, ref_frame="BASE")


async def test_jog_produce_failure_clears_pending(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_jog_command", _fake_produce(False))
    await TeachingPendantService.enable_session()

    with pytest.raises(JogProduceError):
        await TeachingPendantService.request_jog(space="TASK", axis="X", direction=1, step_size=5, ref_frame="BASE")

    assert runtime.teaching_pendant.has_pending() is False


async def test_jog_failed_event_clears_pending_and_keeps_session(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_jog_command", _fake_produce(True))
    await TeachingPendantService.enable_session()
    jog_id = await TeachingPendantService.request_jog(
        space="TASK", axis="X", direction=1, step_size=5, ref_frame="BASE"
    )

    await TeachingPendantService.handle_jog_failed(jog_id, "NOT_REACHABLE")

    assert runtime.teaching_pendant.pending_jog_id is None
    assert runtime.teaching_pendant.enabled is True  # TP-10: 세션은 유지된다


async def test_unknown_jog_id_event_is_ignored(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_jog_command", _fake_produce(True))
    await TeachingPendantService.enable_session()
    jog_id = await TeachingPendantService.request_jog(
        space="TASK", axis="X", direction=1, step_size=5, ref_frame="BASE"
    )

    await TeachingPendantService.handle_jog_complete("unknown-id", [1, 2, 3, 0, 0, 0])

    # 알 수 없는 jog_id는 무시되고, 실제 pending은 그대로 남아있어야 한다.
    assert runtime.teaching_pendant.pending_jog_id == jog_id


# ---- 그리퍼 (TP-12/TP-13) ----


async def test_gripper_request_success(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_gripper_command", _fake_produce(True))
    await TeachingPendantService.enable_session()

    gripper_cmd_id = await TeachingPendantService.request_gripper(action="CLOSE")
    assert runtime.teaching_pendant.pending_gripper_cmd_id == gripper_cmd_id

    await TeachingPendantService.handle_gripper_complete(gripper_cmd_id, "CLOSE")
    assert runtime.teaching_pendant.pending_gripper_cmd_id is None
    assert runtime.teaching_pendant.gripper_state == "CLOSE"


async def test_gripper_request_failure_keeps_session(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_gripper_command", _fake_produce(True))
    await TeachingPendantService.enable_session()

    gripper_cmd_id = await TeachingPendantService.request_gripper(action="OPEN")
    await TeachingPendantService.handle_gripper_failed(gripper_cmd_id, "TIMEOUT")

    assert runtime.teaching_pendant.pending_gripper_cmd_id is None
    assert runtime.teaching_pendant.enabled is True


async def test_gripper_produce_failure_raises(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_gripper_command", _fake_produce(False))
    await TeachingPendantService.enable_session()

    with pytest.raises(GripperProduceError):
        await TeachingPendantService.request_gripper(action="OPEN")


# ---- 정지 ----


async def test_stop_rejected_when_session_inactive():
    with pytest.raises(SessionInactiveError):
        await TeachingPendantService.request_stop()


async def test_stop_accepted_when_session_active():
    await TeachingPendantService.enable_session()
    result = await TeachingPendantService.request_stop()
    assert result["ok"] is True


# ---- 작업요청(WorkRequestService)과의 상호 배제 (PRD 3장 B) ----


async def test_work_request_stays_waiting_during_jog_session(monkeypatch):
    produced = []

    async def _fake_load(**kwargs):
        produced.append(kwargs)
        return True

    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_load)
    await _occupy(2)
    await TeachingPendantService.enable_session()

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)
        assert order.status == OrderStatus.WAITING

    assert produced == []  # SQS LOAD가 전혀 발행되지 않아야 한다

    async with AsyncSessionLocal() as session:
        board = await session.get(BoardStock, 2)
        assert board.status == BoardStockStatus.OCCUPIED  # 예약도 건드리지 않는다

        tasks = (await session.execute(select(RobotTask))).scalars().all()
        assert tasks == []


async def test_work_request_dispatches_normally_after_session_disabled(monkeypatch):
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(True))
    await _occupy(2)

    await TeachingPendantService.enable_session()
    await TeachingPendantService.disable_session()

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)
        assert order.status == OrderStatus.DISPATCHING

    async with AsyncSessionLocal() as session:
        board = await session.get(BoardStock, 2)
        assert board.status == BoardStockStatus.RESERVED

        task = (await session.execute(select(RobotTask))).scalars().one()
        assert task.start_pos_id == 2
