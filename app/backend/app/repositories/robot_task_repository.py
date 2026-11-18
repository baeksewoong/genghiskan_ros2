from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ACTIVE_TASK_STATUSES
from app.models import RobotTask
from app.repositories.base import lock_for_update


class RobotTaskRepository:
    """robot_tasks 테이블 접근을 전담한다."""

    @staticmethod
    def add(session: AsyncSession, task: RobotTask) -> None:
        session.add(task)

    @staticmethod
    async def get_active_real_robot_task_locked(session: AsyncSession) -> RobotTask | None:
        """실물 로봇(작업요청/SQS) 경로 전용 — "현재 실물 로봇에 진행 중인 작업이
        있는지"를 찾는다 (PRD: assets/docs/prd-teaching-pendant.md 3장 A/B). 티칭
        팬던트(조그) 세션 활성화 요청과 작업요청 생성(WorkRequestService.create)
        양쪽이 상호 배제 판단에 이 메서드를 쓴다.

        작업요청 경로 작업은 start_pos_id가 항상 채워져 있으므로 그 행만 본다."""
        stmt = select(RobotTask).where(
            RobotTask.status.in_(ACTIVE_TASK_STATUSES), RobotTask.start_pos_id.isnot(None)
        )
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def get_active_load_for_order_locked(session: AsyncSession, order_id: int) -> RobotTask | None:
        """작업요청(SQS) 경로의 success_load1/fail_load1/재시도 처리용: 해당 주문의
        활성 LOAD 작업을 찾는다."""
        stmt = (
            select(RobotTask)
            .where(
                RobotTask.order_id == order_id,
                RobotTask.status.in_(ACTIVE_TASK_STATUSES),
            )
            .order_by(RobotTask.id.desc())
            .limit(1)
        )
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

