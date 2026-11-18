from datetime import datetime, timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.enums import OrderStatus
from app.models import Order
from app.services.order_service import OrderNotPickupableError, OrderService
from app.services.timer_service import TimerService

pytestmark = pytest.mark.asyncio


async def _make_ready_for_pickup_order() -> int:
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        order = Order(
            user_id=1,
            shape="SQUARE",
            print_duration_sec=40,
            status=OrderStatus.READY_FOR_PICKUP,
            created_at=now - timedelta(hours=1),
            print_completed_at=now - timedelta(hours=1),
            ready_at=now - timedelta(hours=1),  # 오래 지났어도 자동 수령되지 않아야 한다
            updated_at=now,
        )
        session.add(order)
        await session.flush()
        order_id = order.id
        await session.commit()
        return order_id


async def test_timer_sweep_no_longer_auto_picks_up_orders():
    """수령대에 오래 있어도 자동으로 수령 처리되지 않아야 한다 — 사람이 "수령하기"를 눌러야 한다."""
    order_id = await _make_ready_for_pickup_order()

    await TimerService._sweep_print_timers()

    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id)
        assert order.status == OrderStatus.READY_FOR_PICKUP
        assert order.picked_up_at is None


async def test_pick_up_marks_order_picked_up():
    order_id = await _make_ready_for_pickup_order()

    async with AsyncSessionLocal() as session:
        order = await OrderService.pick_up(session, order_id)
        assert order.status == OrderStatus.PICKED_UP
        assert order.picked_up_at is not None

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order_id)
        assert refreshed.status == OrderStatus.PICKED_UP


async def test_pick_up_rejects_order_not_ready_for_pickup():
    async with AsyncSessionLocal() as session:
        order = Order(
            user_id=1,
            shape="SQUARE",
            print_duration_sec=40,
            status=OrderStatus.PRINTING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(order)
        await session.flush()
        order_id = order.id
        await session.commit()

    async with AsyncSessionLocal() as session:
        with pytest.raises(OrderNotPickupableError):
            await OrderService.pick_up(session, order_id)

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order_id)
        assert refreshed.status == OrderStatus.PRINTING


async def test_pick_up_rejects_unknown_order_id():
    async with AsyncSessionLocal() as session:
        with pytest.raises(OrderNotPickupableError):
            await OrderService.pick_up(session, 999999)
