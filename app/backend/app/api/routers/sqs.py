from fastapi import APIRouter

from app.services.sqs_monitor_service import SqsMonitorService

router = APIRouter(prefix="/api/sqs", tags=["sqs"])


@router.get("/status")
async def sqs_status() -> dict:
    return await SqsMonitorService.status()
