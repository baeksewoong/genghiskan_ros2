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
        팬던트(조그) 세션 활성화 요청, 작업요청 생성(WorkRequestService.create)의
        load1 디스패치, unload1 디스패치(dispatch_pending_robot_work) 모두 이
        메서드로 상호 배제를 판단한다.

        LOAD 작업은 start_pos_id, UNLOAD 작업은 sd_pos_id(printer_slot)만 채워져
        있다는 차이만 있을 뿐, 둘 다 success_load1/success_unload1 수신 시
        RUNNING, success_load2/success_unload2 수신 시 SUCCEEDED로 전이한다 —
        따라서 상태(ACTIVE_TASK_STATUSES)만 보면 LOAD/UNLOAD 구분 없이 "로봇이
        지금 이 작업의 1단계~2단계 사이에 있다"는 뜻이 된다. LOAD1~LOAD2,
        UNLOAD1~UNLOAD2는 각각 한 세트이므로, 이 행이 있는 동안은 다른 작업을
        새로 디스패치하면 안 된다."""
        stmt = select(RobotTask).where(RobotTask.status.in_(ACTIVE_TASK_STATUSES))
        return (await session.execute(lock_for_update(stmt, session))).scalars().first()

    @staticmethod
    async def get_active_task_for_order_locked(session: AsyncSession, order_id: int) -> RobotTask | None:
        """작업요청(SQS) 경로의 success_load1/success_unload1/fail_load1/재시도
        처리용: 해당 주문의 활성 로봇 작업(LOAD 또는 UNLOAD)을 찾는다."""
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

