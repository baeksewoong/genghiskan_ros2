import asyncio
import logging
from datetime import datetime

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.events import broadcast_to_web
from app.repositories.order_repository import OrderRepository
from app.repositories.printer_repository import PrinterRepository
from app.services.order_presenter import build_order_out
from app.services.printer_presenter import build_printer_out
from app.services.work_request_service import WorkRequestService

logger = logging.getLogger(__name__)


class TimerService:
    """출력 타이머를 주기적으로 점검해, 끝난 출력은 PRINT_DONE으로 바꾼다.

    unload1은 여기서 바로 보내지 않는다 — LOAD1~LOAD2, UNLOAD1~UNLOAD2는 각각
    한 세트로 묶여야 해서, 로봇이 다른 작업 중이면 끼어들면 안 되기 때문이다
    (work_request_service.WorkRequestService.dispatch_pending_robot_work가
    로봇 점유 여부를 확인해 unload1을 보내거나, 바쁘면 보류한다). 매 틱마다
    그 함수를 호출해 두 번 다 밀린 작업이 자연히 이어지게 한다.

    DB의 timer_ends_at을 매 틱마다 그대로 읽어 판정하므로, 서버가 재시작돼도
    별도 복원 로직 없이 자연히 복구된다."""

    @staticmethod
    async def _sweep_print_timers() -> bool:
        now = datetime.utcnow()
        changed = False
        async with AsyncSessionLocal() as session:
            printers = await PrinterRepository.get_expired_printing(session, now)
            for printer in printers:
                order = await OrderRepository.get(session, printer.current_order_id)
                if order is None:
                    continue
                order.mark_print_done(now)
                printer.mark_done(now)

                await broadcast_to_web(
                    session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
                )
                await broadcast_to_web(
                    session, "printer.updated", (await build_printer_out(session, printer)).model_dump(mode="json")
                )
                changed = True
            await session.commit()
        return changed

    @staticmethod
    async def sweep_loop() -> None:
        while True:
            await asyncio.sleep(settings.timer_sweep_interval_sec)
            try:
                await TimerService._sweep_print_timers()
                # 방금 PRINT_DONE된 주문이 있든 없든, 로봇이 비어 있다면 밀린
                # unload1/load1을 이어서 시도한다.
                await WorkRequestService.dispatch_pending_robot_work()
            except Exception:
                # 한 사이클의 오류가 스윕 루프 전체를 멈추지 않도록 한다.
                logger.exception("timer sweep cycle failed")
