from datetime import datetime, timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.enums import OrderStatus, PrinterStatus, Shape, TaskStatus
from app.models import Order, Printer, RobotTask, User
from app.services.sqs_producer_service import SqsProducerService
from app.services.timer_service import TimerService
from app.services.work_request_service import WorkRequestService

pytestmark = pytest.mark.asyncio


async def _make_printing_order(*, start_pos_id: int | None, slot: int = 1) -> Order:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        user = User(name="tester", created_at=now)
        session.add(user)
        await session.flush()

        order = Order(
            user_id=user.id,
            shape=Shape.TRIANGLE,
            print_duration_sec=30,
            status=OrderStatus.PRINTING,
            printer_slot=slot,
            created_at=now,
            started_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.flush()

        printer = await session.get(Printer, slot)
        printer.status = PrinterStatus.PRINTING
        printer.current_order_id = order.id
        printer.timer_ends_at = now - timedelta(seconds=1)  # 이미 만료됨
        printer.updated_at = now

        task = RobotTask(
            order_id=order.id,
            printer_slot=slot,
            status=TaskStatus.SUCCEEDED,
            start_pos_id=start_pos_id,
            sd_pos_id=slot if start_pos_id is not None else None,
            dispatched_at=now,
            started_at=now,
            finished_at=now,
        )
        session.add(task)

        await session.commit()
        return order


async def test_print_done_sends_unload1_for_sqs_dispatched_order(monkeypatch):
    """_sweep_print_timers 자체는 unload1을 보내지 않는다 — LOAD1~LOAD2,
    UNLOAD1~UNLOAD2가 각각 한 세트로 묶여야 해서, 로봇이 비어 있는지는
    dispatch_pending_robot_work가 판단한다(work_request_service 참고).
    여기서는 로봇이 비어 있으므로 바로 unload1이 나간다."""
    sent: list[dict] = []

    async def _fake_produce_unload(*, work_id, sd_pos_id):
        sent.append({"work_id": work_id, "sd_pos_id": sd_pos_id})
        return True

    monkeypatch.setattr(SqsProducerService, "produce_unload_command", _fake_produce_unload)

    order = await _make_printing_order(start_pos_id=3)

    await TimerService._sweep_print_timers()
    assert sent == []  # 스윕만으로는 아직 보내지 않는다

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order.id)
        assert refreshed.status == OrderStatus.PRINT_DONE

        printer = await session.get(Printer, 1)
        assert printer.status == PrinterStatus.DONE

    await WorkRequestService.dispatch_pending_robot_work()

    # 완성품이 놓인 printer.slot(여기서는 1)으로 unload1이 나간다.
    assert sent == [{"work_id": order.id, "sd_pos_id": 1}]


async def test_dispatch_pending_robot_work_serializes_unload1_across_printers(monkeypatch):
    """프린터 두 대가 같은 스윕 틱에 동시에 타이머 만료되더라도, unload1은 한 번에
    하나씩만 나간다 — 로봇이 앞 주문의 unload1~unload2를 마치기 전에 다른 프린터의
    unload1이 끼어들면 안 된다."""
    sent_unload1: list[dict] = []
    sent_unload2: list[dict] = []

    async def _fake_produce_unload(*, work_id, sd_pos_id):
        sent_unload1.append({"work_id": work_id, "sd_pos_id": sd_pos_id})
        return True

    async def _fake_produce_unload2(*, work_id, receive_pos_id):
        sent_unload2.append({"work_id": work_id, "receive_pos_id": receive_pos_id})
        return True

    monkeypatch.setattr(SqsProducerService, "produce_unload_command", _fake_produce_unload)
    monkeypatch.setattr(SqsProducerService, "produce_unload2_command", _fake_produce_unload2)

    first = await _make_printing_order(start_pos_id=None, slot=1)
    second = await _make_printing_order(start_pos_id=None, slot=2)

    await TimerService._sweep_print_timers()
    assert sent_unload1 == []  # 스윕만으로는 아직 보내지 않는다

    await WorkRequestService.dispatch_pending_robot_work()

    # 둘 다 PRINT_DONE이지만, 로봇은 하나씩만 처리할 수 있으므로 한 쪽만 unload1이 나간다.
    assert len(sent_unload1) == 1
    dispatched_id = sent_unload1[0]["work_id"]
    other_id = second.id if dispatched_id == first.id else first.id

    # 로봇이 아직 dispatched_id의 unload1~unload2 사이라, 다시 호출해도 늘어나지 않는다.
    await WorkRequestService.dispatch_pending_robot_work()
    assert len(sent_unload1) == 1

    # 그 주문의 unload1~unload2가 끝나 로봇이 비면, 남은 주문이 자동으로 이어진다.
    await WorkRequestService.handle_unload1_success(dispatched_id)
    await WorkRequestService.handle_unload2_success(dispatched_id)

    assert len(sent_unload1) == 2
    assert sent_unload1[1]["work_id"] == other_id
