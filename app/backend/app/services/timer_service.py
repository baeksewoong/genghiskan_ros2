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
from app.services.sqs_producer_service import SqsProducerService

logger = logging.getLogger(__name__)


class TimerService:
    """출력 타이머를 주기적으로 점검해, 끝난 출력은 PRINT_DONE으로 바꾸고 unload1을 보낸다.

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

                # 출력이 끝나면 robot-commands에 unload1(프린터에서 완성품 꺼내기)을 보낸다.
                # TODO: 실제 프린터 슬롯(printer.slot)이 아니라 1로 하드코딩해 발행 중 — 테스트용 임시 조치.
                await SqsProducerService.produce_unload_command(work_id=order.id, sd_pos_id=1)

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
            except Exception:
                # 한 사이클의 오류가 스윕 루프 전체를 멈추지 않도록 한다.
                logger.exception("timer sweep cycle failed")
