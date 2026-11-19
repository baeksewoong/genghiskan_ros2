from datetime import datetime, timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.enums import OrderStatus, PrinterStatus, Shape, TaskStatus
from app.models import Order, Printer, RobotTask, User
from app.services.sqs_producer_service import SqsProducerService
from app.services.timer_service import TimerService

pytestmark = pytest.mark.asyncio


async def _make_printing_order(*, start_pos_id: int | None) -> Order:
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
            printer_slot=1,
            created_at=now,
            started_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.flush()

        printer = await session.get(Printer, 1)
        printer.status = PrinterStatus.PRINTING
        printer.current_order_id = order.id
        printer.timer_ends_at = now - timedelta(seconds=1)  # 이미 만료됨
        printer.updated_at = now

        task = RobotTask(
            order_id=order.id,
            printer_slot=1,
            status=TaskStatus.SUCCEEDED,
            start_pos_id=start_pos_id,
            sd_pos_id=1 if start_pos_id is not None else None,
            dispatched_at=now,
            started_at=now,
            finished_at=now,
        )
        session.add(task)

        await session.commit()
        return order


async def test_print_done_sends_unload1_for_sqs_dispatched_order(monkeypatch):
    sent: list[dict] = []

    async def _fake_produce_unload(*, work_id, sd_pos_id):
        sent.append({"work_id": work_id, "sd_pos_id": sd_pos_id})
        return True

    monkeypatch.setattr(SqsProducerService, "produce_unload_command", _fake_produce_unload)

    order = await _make_printing_order(start_pos_id=3)

    await TimerService._sweep_print_timers()

    # 테스트용 임시 조치로 sd_pos_id를 1로 하드코딩해 발행한다 (실제 printer.slot=1과 무관).
    assert sent == [{"work_id": order.id, "sd_pos_id": 1}]

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order.id)
        assert refreshed.status == OrderStatus.PRINT_DONE

        printer = await session.get(Printer, 1)
        assert printer.status == PrinterStatus.DONE
