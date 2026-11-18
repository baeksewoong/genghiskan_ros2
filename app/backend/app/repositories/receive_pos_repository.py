from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ReceivePosStatus
from app.models import ReceivePos
from app.repositories.base import lock_for_update


class ReceivePosRepository:
    """receive_pos(수령대 1, 2 현황) 테이블 접근을 전담한다."""

    @staticmethod
    async def list_all(session: AsyncSession) -> list[ReceivePos]:
        stmt = select(ReceivePos).order_by(ReceivePos.pos_id)
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def ensure_slots(session: AsyncSession, pos_ids: tuple[int, ...], now: datetime) -> None:
        existing = {r.pos_id for r in (await session.execute(select(ReceivePos))).scalars().all()}
        for pos_id in pos_ids:
            if pos_id not in existing:
                session.add(ReceivePos(pos_id=pos_id, status=ReceivePosStatus.EMPTY, updated_at=now))

    @staticmethod
    async def first_empty_locked(session: AsyncSession) -> ReceivePos | None:
        """비어있는 수령대 중 번호가 가장 작은 곳(1번 우선)을 잠금과 함께 가져온다."""
        stmt = (
            select(ReceivePos)
            .where(ReceivePos.status == ReceivePosStatus.EMPTY)
            .order_by(ReceivePos.pos_id)
            .limit(1)
        )
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def get_by_order_locked(session: AsyncSession, order_id: int) -> ReceivePos | None:
        stmt = select(ReceivePos).where(ReceivePos.current_order_id == order_id)
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()
