from fastapi import APIRouter

from app.services.sqs_monitor_service import SqsMonitorService

router = APIRouter(prefix="/api/sqs", tags=["sqs"])


@router.get("/status")
async def sqs_status() -> dict:
    return await SqsMonitorService.status()


@router.get("/history")
async def sqs_history(limit: int = 200) -> list[dict]:
    return await SqsMonitorService.history(limit)
