from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import broadcast_to_web
from app.enums import OrderStatus
from app.models import InvalidStateTransitionError, Order
from app.repositories.order_repository import OrderRepository
from app.repositories.receive_pos_repository import ReceivePosRepository
from app.services.order_presenter import build_order_out
from app.services.work_request_service import WorkRequestService


class OrderNotPickupableError(Exception):
    """수령하기 대상 주문을 찾을 수 없거나, 아직 수령대(READY_FOR_PICKUP)에
    올라오지 않았을 때."""

    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"order {order_id} is not ready for pickup")


class OrderService:
    @staticmethod
    async def list_orders(session: AsyncSession, status: OrderStatus | None, limit: int) -> list[Order]:
        return await OrderRepository.list_recent(session, status, limit)

    @staticmethod
    async def pick_up(session: AsyncSession, order_id: int) -> Order:
        """수령대에서 "수령하기"를 눌렀을 때만 PICKED_UP으로 전환한다."""
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

        # 이 주문이 올라가 있던 수령대를 비운다.
        receive_pos = await ReceivePosRepository.get_by_order_locked(session, order_id)
        if receive_pos is not None:
            receive_pos.release(now)
        await session.flush()

        await broadcast_to_web(session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json"))
        if receive_pos is not None:
            await broadcast_to_web(
                session, "receive_pos.updated", await WorkRequestService._receive_pos_snapshot(session)
            )
        await session.commit()

        # 수령대 자리가 났다 — 수령대가 가득 차서 대기 중인 완성품이 있으면 unload2를 이어서
        # 보낸다(로봇이 이미 집어서 들고 있는 드문 경우의 방어 코드). 그리고 수령대가
        # 가득 차서 unload1조차 보내지 못하고 PRINT_DONE으로 대기 중인 주문이 있으면
        # 그것도 이어서 디스패치한다. (작업요청 SQS 경로 전용. 대기 주문이 없으면
        # 아무것도 하지 않는다.)
        await WorkRequestService.dispatch_pending_unload2()
        await WorkRequestService.dispatch_pending_robot_work()
        return order
