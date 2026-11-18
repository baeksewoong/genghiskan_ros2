from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import PrinterStatus
from app.models import Printer
from app.repositories.base import lock_for_update


class PrinterRepository:
    """printers 테이블 접근을 전담한다."""

    @staticmethod
    async def get(session: AsyncSession, slot: int) -> Printer | None:
        return await session.get(Printer, slot)

    @staticmethod
    async def list_all(session: AsyncSession) -> list[Printer]:
        stmt = select(Printer).order_by(Printer.slot)
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def ensure_slots(session: AsyncSession, slots: tuple[int, ...], now: datetime) -> None:
        existing = {p.slot for p in (await session.execute(select(Printer))).scalars().all()}
        for slot in slots:
            if slot not in existing:
                session.add(Printer(slot=slot, status=PrinterStatus.EMPTY, updated_at=now))

    @staticmethod
    async def first_empty_locked(session: AsyncSession) -> Printer | None:
        stmt = select(Printer).where(Printer.status == PrinterStatus.EMPTY).order_by(Printer.slot)
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def get_locked(session: AsyncSession, slot: int) -> Printer | None:
        stmt = select(Printer).where(Printer.slot == slot)
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def get_expired_printing(session: AsyncSession, now: datetime) -> list[Printer]:
        stmt = select(Printer).where(Printer.status == PrinterStatus.PRINTING, Printer.timer_ends_at <= now)
        return list((await session.execute(stmt)).scalars().all())
