from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas import OrderCreateRequest, OrderOut
from app.services.order_presenter import build_order_out
from app.services.work_request_service import (
    BoardEmptyError,
    LoadRetryNotFoundError,
    SqsProduceError,
    UnloadRetryNotFoundError,
    WorkRequestService,
)

router = APIRouter(prefix="/api/work-requests", tags=["work-requests"])


@router.post("", response_model=OrderOut, status_code=201)
async def create_work_request(
    req: OrderCreateRequest, session: AsyncSession = Depends(get_session)
) -> OrderOut:
    try:
        order = await WorkRequestService.create(session, req.shape, customer_name=req.customer_name)
        return await build_order_out(session, order)
    except BoardEmptyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "BOARD_EMPTY",
                "message": "적재대에 베드가 비어있습니다",
            },
        ) from exc
    except SqsProduceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "SQS_PRODUCE_FAILED",
                "message": "로봇에 작업을 전달하지 못했습니다. 운영자 확인이 필요합니다.",
                "order_id": exc.order_id,
            },
        ) from exc


@router.post("/{work_id}/retry-load", status_code=200)
async def retry_load(work_id: int) -> dict:
    """베드 집기 실패 알럿에서 사람이 "확인"을 누르면 같은 LOAD 명령을 다시 보낸다."""
    try:
        await WorkRequestService.retry_load(work_id)
    except LoadRetryNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "LOAD_TASK_NOT_FOUND",
                "message": "재시도할 작업을 찾을 수 없습니다",
                "work_id": exc.work_id,
            },
        ) from exc
    except SqsProduceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "SQS_PRODUCE_FAILED",
                "message": "로봇에 작업을 다시 전달하지 못했습니다. 운영자 확인이 필요합니다.",
                "order_id": exc.order_id,
            },
        ) from exc
    return {"ok": True}


@router.post("/{work_id}/retry-unload", status_code=200)
async def retry_unload(work_id: int) -> dict:
    """완성품 집기 실패 알럿에서 사람이 "확인"을 누르면 같은 unload1 명령을 다시 보낸다."""
    try:
        await WorkRequestService.retry_unload1(work_id)
    except UnloadRetryNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "UNLOAD_TASK_NOT_FOUND",
                "message": "재시도할 작업을 찾을 수 없습니다",
                "work_id": exc.work_id,
            },
        ) from exc
    except SqsProduceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "SQS_PRODUCE_FAILED",
                "message": "로봇에 작업을 다시 전달하지 못했습니다. 운영자 확인이 필요합니다.",
                "order_id": exc.order_id,
            },
        ) from exc
    return {"ok": True}
