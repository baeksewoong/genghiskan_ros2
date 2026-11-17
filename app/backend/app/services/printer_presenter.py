"""PrinterOut 직렬화 전용 헬퍼. 작업대 현황 UI에 손님 이름을 보여주기 위해,
current_order_id가 있으면 그 주문의 손님 이름(customer_name)도 함께 채운다.
printer.updated를 브로드캐스트하는 모든 곳에서 이 함수를 통해 직렬화해야
화면에 표시되는 이름이 항상 최신 상태로 맞는다."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, Printer, User
from app.schemas import PrinterOut


async def build_printer_out(session: AsyncSession, printer: Printer) -> PrinterOut:
    customer_name: str | None = None
    if printer.current_order_id is not None:
        stmt = select(User.name).join(Order, Order.user_id == User.id).where(Order.id == printer.current_order_id)
        customer_name = (await session.execute(stmt)).scalar_one_or_none()

    data = PrinterOut.model_validate(printer).model_dump()
    data["customer_name"] = customer_name
    return PrinterOut(**data)
