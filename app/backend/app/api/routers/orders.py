from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.enums import OrderStatus
from app.schemas import OrderOut
from app.services.order_presenter import build_order_out
from app.services.order_service import OrderNotPickupableError, OrderService

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: OrderStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[OrderOut]:
    orders = await OrderService.list_orders(session, status, limit)
    return [await build_order_out(session, o) for o in orders]


@router.post("/{order_id}/pickup", response_model=OrderOut)
async def pick_up_order(order_id: int, session: AsyncSession = Depends(get_session)) -> OrderOut:
    """수령대 "수령하기" 버튼 — 눌렀을 때만 주문을 수령대에서 내린다."""
    try:
        order = await OrderService.pick_up(session, order_id)
    except OrderNotPickupableError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ORDER_NOT_PICKUPABLE",
                "message": "수령 대상 주문을 찾을 수 없습니다",
                "order_id": exc.order_id,
            },
        ) from exc
    return await build_order_out(session, order)
