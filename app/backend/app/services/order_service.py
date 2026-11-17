import random
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import broadcast_to_web
from app.enums import OrderSource, OrderStatus, Shape
from app.models import InvalidStateTransitionError, Order
from app.repositories.order_repository import OrderRepository
from app.repositories.user_repository import UserRepository
from app.services.dispatcher_service import DispatcherService
from app.services.order_presenter import build_order_out

_SHAPE_CHOICES = list(Shape)


class OrderNotPickupableError(Exception):
    """수령하기 대상 주문을 찾을 수 없거나, 아직 수령대(READY_FOR_PICKUP)에
    올라오지 않았을 때."""

    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"order {order_id} is not ready for pickup")


class OrderService:
    @staticmethod
    async def create_order(
        session: AsyncSession,
        shape: Shape | None,
        source: OrderSource,
        customer_name: str | None = None,
    ) -> Order:
        chosen_shape = shape or random.choice(_SHAPE_CHOICES)
        now = datetime.utcnow()

        name = customer_name or f"손님-{random.randint(0, 9999):04d}"
        user = await UserRepository.add(session, name=name, created_at=now)

        order = Order.create_new(user_id=user.id, shape=chosen_shape, source=source, now=now)
        OrderRepository.add(session, order)
        await session.flush()

        await broadcast_to_web(session, "order.created", (await build_order_out(session, order)).model_dump(mode="json"))
        await session.commit()

        await DispatcherService.run_cycle()
        # 디스패처가 다른 세션으로 이 주문을 즉시 LOAD 디스패치했을 수 있으므로 최신 상태로 갱신한다.
        await session.refresh(order)
        return order

    @staticmethod
    async def list_orders(session: AsyncSession, status: OrderStatus | None, limit: int) -> list[Order]:
        return await OrderRepository.list_recent(session, status, limit)

    @staticmethod
    async def pick_up(session: AsyncSession, order_id: int) -> Order:
        """수령대에서 "수령하기"를 눌렀을 때만 PICKED_UP으로 전환한다 — 더 이상
        pickup_delay_sec이 지나면 자동으로 전환되지 않는다."""
        order = await OrderRepository.get_locked(session, order_id)
        if order is None:
            await session.rollback()
            raise OrderNotPickupableError(order_id)

        now = datetime.utcnow()
        try:
            order.mark_picked_up(now)
        except InvalidStateTransitionError:
            await session.rollback()
            raise OrderNotPickupableError(order_id) from None
        await session.flush()

        await broadcast_to_web(session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json"))
        await session.commit()
        return order
