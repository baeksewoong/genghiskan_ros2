from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ACTIVE_ORDER_STATUSES, OrderSource, OrderStatus
from app.models import Order
from app.repositories.base import lock_for_update


class OrderRepository:
    """orders 테이블 접근을 전담한다. 상태 변경(mutation)은 Order 엔티티의
    전이 메서드(mark_loading 등)가 책임지고, 서비스 계층은 그 호출과 트랜잭션
    커밋만 오케스트레이션한다."""

    @staticmethod
    def add(session: AsyncSession, order: Order) -> None:
        session.add(order)

    @staticmethod
    async def get(session: AsyncSession, order_id: int) -> Order | None:
        return await session.get(Order, order_id)

    @staticmethod
    async def get_locked(session: AsyncSession, order_id: int) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def list_recent(
        session: AsyncSession, status: OrderStatus | None, limit: int
    ) -> list[Order]:
        stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(Order.status == status)
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def get_waiting(session: AsyncSession) -> list[Order]:
        stmt = select(Order).where(Order.status == OrderStatus.WAITING).order_by(Order.created_at)
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def get_active(session: AsyncSession) -> list[Order]:
        stmt = (
            select(Order).where(Order.status.in_(ACTIVE_ORDER_STATUSES)).order_by(Order.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def get_pickup(session: AsyncSession) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.status == OrderStatus.READY_FOR_PICKUP)
            .order_by(Order.ready_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def oldest_waiting_locked(session: AsyncSession) -> Order | None:
        """가상 로봇(/ws/bridge) 경로의 DispatcherService 전용. 작업요청(SQS) 경로
        (source=WORK_REQUEST) 주문은 제외한다 — 그 경로가 board_stock 부족/빈 프린터
        없음으로 WAITING에 남겨둔 주문을 여기서 board 체크 없이 집어가 버리면, SQS로
        가야 할 주문이 가상 로봇으로 완료돼 버린다."""
        stmt = (
            select(Order)
            .where(Order.status == OrderStatus.WAITING, Order.source != OrderSource.WORK_REQUEST)
            .order_by(Order.created_at)
        )
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def count_by_status(session: AsyncSession, status: OrderStatus) -> int:
        stmt = select(func.count()).where(Order.status == status)
        return (await session.execute(stmt)).scalar_one()

    @staticmethod
    async def wait_duration_rows(session: AsyncSession) -> list[tuple]:
        stmt = select(Order.created_at, Order.started_at).where(Order.started_at.isnot(None))
        return list((await session.execute(stmt)).all())

    @staticmethod
    async def print_duration_rows(session: AsyncSession) -> list[tuple]:
        stmt = select(Order.started_at, Order.print_completed_at).where(
            Order.started_at.isnot(None), Order.print_completed_at.isnot(None)
        )
        return list((await session.execute(stmt)).all())

    @staticmethod
    async def pickup_duration_rows(session: AsyncSession) -> list[tuple]:
        stmt = select(Order.ready_at, Order.picked_up_at).where(Order.picked_up_at.isnot(None))
        return list((await session.execute(stmt)).all())
