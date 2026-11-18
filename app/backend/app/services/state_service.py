from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.order_repository import OrderRepository
from app.repositories.printer_repository import PrinterRepository
from app.schemas import StateSnapshot
from app.services.order_presenter import build_order_out
from app.services.printer_presenter import build_printer_out


class StateService:
    @staticmethod
    async def build_snapshot(session: AsyncSession) -> StateSnapshot:
        printers = await PrinterRepository.list_all(session)
        waiting = await OrderRepository.get_waiting(session)
        active = await OrderRepository.get_active(session)
        pickup = await OrderRepository.get_pickup(session)

        return StateSnapshot(
            printers=[await build_printer_out(session, p) for p in printers],
            waiting_orders=[await build_order_out(session, o) for o in waiting],
            active_orders=[await build_order_out(session, o) for o in active],
            pickup_orders=[await build_order_out(session, o) for o in pickup],
        )
