from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ACTIVE_TASK_STATUSES, TaskType
from app.models import RobotTask
from app.repositories.base import lock_for_update


class RobotTaskRepository:
    """robot_tasks 테이블 접근을 전담한다."""

    @staticmethod
    def add(session: AsyncSession, task: RobotTask) -> None:
        session.add(task)

    @staticmethod
    async def get(session: AsyncSession, task_id: int) -> RobotTask | None:
        return await session.get(RobotTask, task_id)

    @staticmethod
    async def get_active_locked(session: AsyncSession) -> RobotTask | None:
        """가상 로봇(/ws/bridge) 경로 전용 — "현재 그 로봇에 내려간 작업 하나"를 찾는다.
        작업요청(SQS) 경로의 작업은 start_pos_id가 항상 채워져 있어 여기서 제외된다
        (그 경로는 printer_slot이 success_load1 전엔 비어있을 수 있어, 포함시키면
        이 함수를 쓰는 되돌리기/게이팅 로직이 깨진다)."""
        stmt = select(RobotTask).where(
            RobotTask.status.in_(ACTIVE_TASK_STATUSES), RobotTask.start_pos_id.is_(None)
        )
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def get_active_real_robot_task_locked(session: AsyncSession) -> RobotTask | None:
        """실물 로봇(작업요청/SQS) 경로 전용 — "현재 실물 로봇에 진행 중인 작업이
        있는지"를 찾는다 (PRD: assets/docs/prd-teaching-pendant.md 3장 A/B). 티칭
        팬던트(조그) 세션 활성화 요청과 작업요청 생성(WorkRequestService.create)
        양쪽이 상호 배제 판단에 이 메서드를 쓴다.

        get_active_locked()와 정반대로 start_pos_id가 채워진 행만 본다 — 그
        메서드의 주석대로 작업요청 경로 작업은 start_pos_id가 항상 채워져 있어
        가상 로봇 전용 조회에서는 제외되지만, 여기서는 그 작업만 찾아야 한다.
        기존 get_active_locked()는 가상 로봇(/ws/bridge) 전용 동작이 걸려있으니
        건드리지 않는다."""
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
                RobotTask.type == TaskType.LOAD,
                RobotTask.status.in_(ACTIVE_TASK_STATUSES),
            )
            .order_by(RobotTask.id.desc())
            .limit(1)
        )
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def get_load_task_for_order(session: AsyncSession, order_id: int) -> RobotTask | None:
        """상태 무관하게 해당 주문의 가장 최근 LOAD 작업을 찾는다. 작업요청(SQS)
        경로로 디스패치됐는지(start_pos_id가 채워져 있는지) 판별하는 용도 — 예:
        출력 완료 시 robot-commands에 unload1을 보낼지 결정."""
        stmt = (
            select(RobotTask)
            .where(RobotTask.order_id == order_id, RobotTask.type == TaskType.LOAD)
            .order_by(RobotTask.id.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def get_timed_out(session: AsyncSession, deadline: datetime) -> list[RobotTask]:
        stmt = select(RobotTask).where(
            RobotTask.status.in_(ACTIVE_TASK_STATUSES), RobotTask.dispatched_at <= deadline
        )
        return list((await session.execute(stmt)).scalars().all())
