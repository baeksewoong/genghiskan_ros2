"""OrderOut 직렬화 전용 헬퍼. 수령대/대기열 등 UI에 손님 이름을 보여주기 위해,
주문자(User)의 이름(customer_name)도 함께 채운다. order.created/order.updated를
브로드캐스트하는 모든 곳에서 이 함수를 통해 직렬화해야 화면에 표시되는 이름이
항상 최신 상태로 맞는다."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, User
from app.schemas import OrderOut


async def build_order_out(session: AsyncSession, order: Order) -> OrderOut:
    user = await session.get(User, order.user_id)
    data = OrderOut.model_validate(order).model_dump()
    data["customer_name"] = user.name if user is not None else None
    return OrderOut(**data)
