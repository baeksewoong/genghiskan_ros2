"""디스패처: 로봇이 IDLE일 때마다 UNLOAD > LOAD 우선순위로 작업을 하나 고르고
로봇 쪽(/ws/bridge)으로 내려보낸다 (PRD 3장). 여러 리포지토리/엔티티를 넘나드는
유스케이스 orchestration이므로 서비스 계층에 둔다 — 상태 전이 규칙 자체는
Order/Printer/RobotTask 엔티티 메서드로 옮겨져 있다."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.events import broadcast_to_web, send_to_bridge
from app.core.runtime import runtime
from app.enums import ACTIVE_TASK_STATUSES, RobotState, TaskType
from app.models import Order, Printer, RobotTask
from app.repositories.order_repository import OrderRepository
from app.repositories.printer_repository import PrinterRepository
from app.repositories.robot_task_repository import RobotTaskRepository
from app.services.order_presenter import build_order_out
from app.services.printer_presenter import build_printer_out


@dataclass
class _ReservedTask:
    task: RobotTask
    order: Order
    printer: Printer


class DispatcherService:
    @staticmethod
    async def run_cycle() -> None:
        async with runtime.dispatcher_lock:
            await DispatcherService._run_cycle_locked()

    @staticmethod
    async def _run_cycle_locked() -> None:
        if runtime.robot_state != RobotState.IDLE:
            return

        async with AsyncSessionLocal() as session:
            active = await RobotTaskRepository.get_active_locked(session)
            if active is not None:
                await session.rollback()
                return

            reserved = await DispatcherService._try_reserve_unload(session)
            if reserved is None:
                reserved = await DispatcherService._try_reserve_load(session)
                if reserved is None:
                    await session.rollback()
                    return

            await broadcast_to_web(
                session, "order.updated", (await build_order_out(session, reserved.order)).model_dump(mode="json")
            )
            await broadcast_to_web(
                session, "printer.updated", (await build_printer_out(session, reserved.printer)).model_dump(mode="json")
            )
            await session.commit()

            task_id = reserved.task.id
            sent = await send_to_bridge(
                session,
                "task.dispatch",
                {
                    "task_id": task_id,
                    "type": reserved.task.type.value,
                    "slot": reserved.task.printer_slot,
                    "order_id": reserved.task.order_id,
                    # 가상 로봇이 7.7 단계 시간에 곱할 현재 시간 배율 (FR-20).
                    "time_scale": runtime.simulator_time_scale,
                },
            )
            await session.commit()

            if sent:
                runtime.current_task_id = task_id
            else:
                await DispatcherService._revert_unsent_task(task_id)

    @staticmethod
    async def _try_reserve_unload(session: AsyncSession) -> _ReservedTask | None:
        found = await PrinterRepository.get_done_with_order_locked(session)
        if found is None:
            return None
        printer, order = found

        now = datetime.utcnow()
        task = RobotTask.dispatch_unload(order_id=order.id, printer_slot=printer.slot, now=now)
        RobotTaskRepository.add(session, task)
        order.mark_unloading(now)
        printer.start_unloading(now)
        await session.flush()
        return _ReservedTask(task=task, order=order, printer=printer)

    @staticmethod
    async def _try_reserve_load(session: AsyncSession) -> _ReservedTask | None:
        """LOAD 작업을 예약한다."""
        order = await OrderRepository.oldest_waiting_locked(session)
        if order is None:
            return None

        printer = await PrinterRepository.first_empty_locked(session)
        if printer is None:
            return None

        now = datetime.utcnow()
        task = RobotTask.dispatch_load(order_id=order.id, printer_slot=printer.slot, now=now)
        RobotTaskRepository.add(session, task)
        order.mark_loading(now, printer_slot=printer.slot)
        printer.reserve(order.id, now)
        await session.flush()
        return _ReservedTask(task=task, order=order, printer=printer)

    @staticmethod
    async def _revert_unsent_task(task_id: int) -> None:
        """디스패치 직후 브릿지 전송에 실패하면 작업을 취소하고 원래 상태로 되돌린다."""
        async with AsyncSessionLocal() as session:
            task = await RobotTaskRepository.get(session, task_id)
            if task is None or task.status not in ACTIVE_TASK_STATUSES:
                return
            order = await OrderRepository.get(session, task.order_id)
            printer = await PrinterRepository.get(session, task.printer_slot)
            now = datetime.utcnow()

            task.cancel(now)

            if task.type == TaskType.LOAD:
                order.revert_to_waiting(now)
                printer.clear(now)
            else:
                order.revert_to_print_done(now)
                printer.revert_to_done(now)

            await broadcast_to_web(
                session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
            )
            await broadcast_to_web(
                session, "printer.updated", (await build_printer_out(session, printer)).model_dump(mode="json")
            )
            await broadcast_to_web(session, "bridge.connection", {"connected": False})
            await session.commit()

        runtime.robot_state = RobotState.DISCONNECTED
        runtime.bridge_ws = None
        runtime.current_task_id = None
