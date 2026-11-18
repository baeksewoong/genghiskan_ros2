from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EventDirection
from app.models import EventLog


class EventLogRepository:
    """event_logs 테이블 접근을 전담한다 (요구사항 10.1 관측성: 모든 WS 메시지 저장)."""

    @staticmethod
    def add(session: AsyncSession, envelope: dict[str, Any], direction: EventDirection) -> None:
        session.add(
            EventLog(
                event_id=envelope["event_id"],
                type=envelope["type"],
                direction=direction,
                payload=envelope,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    @staticmethod
    async def list_by_type_prefix(session: AsyncSession, prefix: str, limit: int) -> list[EventLog]:
        """SQS 모니터링 페이지의 메시지 히스토리 조회용: type이 prefix로 시작하는
        최근 기록을 최신순으로 가져온다."""
        stmt = (
            select(EventLog)
            .where(EventLog.type.like(f"{prefix}%"))
            .order_by(EventLog.id.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def try_add_unique(
        session: AsyncSession, envelope: dict[str, Any], direction: EventDirection
    ) -> bool:
        """event_id가 이미 존재하면(중복 수신) False를 반환하고 세션을 롤백한다."""
        EventLogRepository.add(session, envelope, direction)
        try:
            await session.flush()
            return True
        except IntegrityError:
            await session.rollback()
            return False
