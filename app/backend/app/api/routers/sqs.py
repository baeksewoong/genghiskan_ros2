import uuid

from fastapi import APIRouter, HTTPException

from app.schemas import Unload2CommandOut, Unload2CommandRequest
from app.services.sqs_monitor_service import SqsMonitorService
from app.services.sqs_producer_service import SqsProducerService

router = APIRouter(prefix="/api/sqs", tags=["sqs"])


@router.get("/status")
async def sqs_status() -> dict:
    return await SqsMonitorService.status()


@router.get("/history")
async def sqs_history(limit: int = 200) -> list[dict]:
    return await SqsMonitorService.history(limit)


@router.post("/commands/unload2", response_model=Unload2CommandOut)
async def send_unload2(req: Unload2CommandRequest) -> Unload2CommandOut:
    """unload2 명령을 robot-commands에 바로 발행한다 (테스트/ROS 2 연동 확인용).

    주문·수령대 상태(DB)는 바꾸지 않는다 — 정상 흐름의 unload2는 success_unload1
    수신 시 서버가 수령대를 배정하면서 자동으로 보낸다. 같은 work_id로 여러 번
    호출해도 매번 실제로 발행되도록 dedup id에 재시도 토큰을 붙인다."""
    produced = await SqsProducerService.produce_unload2_command(
        work_id=req.work_id, receive_pos_id=req.receive_pos_id, retry_token=uuid.uuid4().hex[:12]
    )
    body = {"type": "unload2", "work_id": req.work_id, "receive_pos_id": req.receive_pos_id}
    if not produced:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "SQS_PRODUCE_FAILED",
                "message": "unload2를 발행하지 못했습니다 (COMMAND_QUEUE_URL 미설정 또는 SQS 전송 실패 — SQS 모니터 로그 확인)",
                "body": body,
            },
        )
    return Unload2CommandOut(sent=True, body=body)
