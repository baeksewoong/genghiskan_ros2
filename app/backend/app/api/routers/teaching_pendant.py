from fastapi import APIRouter, HTTPException

from app.schemas import (
    TeachingPendantGripperAccepted,
    TeachingPendantGripperRequest,
    TeachingPendantJogAccepted,
    TeachingPendantJogRequest,
    TeachingPendantSessionOut,
    TeachingPendantSessionRequest,
    TeachingPendantStopOut,
)
from app.services.teaching_pendant_service import (
    GripperProduceError,
    InvalidJogRequestError,
    JogProduceError,
    RobotBusyError,
    SessionInactiveError,
    StepPendingError,
    TeachingPendantService,
)

router = APIRouter(prefix="/api/teaching-pendant", tags=["teaching-pendant"])


def _robot_busy_detail() -> dict:
    return {"error_code": "ROBOT_BUSY", "message": "작업 진행 중이라 조그를 쓸 수 없습니다"}


def _step_conflict_detail(exc: Exception) -> dict:
    """PRD 8.2/6장 — 세션 비활성/이전 스텝 진행 중/실물 로봇 작업 중을 모두 409로
    매핑하되, 운영자에게 보여줄 이유는 구분해서 돌려준다."""
    if isinstance(exc, SessionInactiveError):
        return {"error_code": "SESSION_INACTIVE", "message": "조그 세션이 비활성 상태입니다"}
    if isinstance(exc, StepPendingError):
        return {"error_code": "STEP_PENDING", "message": "이전 스텝이 아직 진행 중입니다"}
    return _robot_busy_detail()


@router.post("/session", response_model=TeachingPendantSessionOut)
async def set_session(req: TeachingPendantSessionRequest) -> TeachingPendantSessionOut:
    try:
        result = await TeachingPendantService.set_session(req.enable)
    except RobotBusyError as exc:
        raise HTTPException(status_code=409, detail=_robot_busy_detail()) from exc
    return TeachingPendantSessionOut(**result)


@router.post("/jog", status_code=202, response_model=TeachingPendantJogAccepted)
async def request_jog(req: TeachingPendantJogRequest) -> TeachingPendantJogAccepted:
    try:
        jog_id = await TeachingPendantService.request_jog(
            space=req.space.value,
            axis=req.axis,
            direction=req.direction,
            step_size=req.step_size,
            ref_frame=req.ref_frame.value if req.ref_frame is not None else None,
        )
    except (SessionInactiveError, StepPendingError, RobotBusyError) as exc:
        raise HTTPException(status_code=409, detail=_step_conflict_detail(exc)) from exc
    except InvalidJogRequestError as exc:
        raise HTTPException(
            status_code=400, detail={"error_code": exc.error_code, "message": exc.message}
        ) from exc
    except JogProduceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "SQS_PRODUCE_FAILED",
                "message": "로봇에 조그 명령을 전달하지 못했습니다. 운영자 확인이 필요합니다.",
            },
        ) from exc
    return TeachingPendantJogAccepted(jog_id=jog_id)


@router.post("/gripper", status_code=202, response_model=TeachingPendantGripperAccepted)
async def request_gripper(req: TeachingPendantGripperRequest) -> TeachingPendantGripperAccepted:
    try:
        gripper_cmd_id = await TeachingPendantService.request_gripper(action=req.action.value)
    except (SessionInactiveError, StepPendingError, RobotBusyError) as exc:
        raise HTTPException(status_code=409, detail=_step_conflict_detail(exc)) from exc
    except InvalidJogRequestError as exc:
        raise HTTPException(
            status_code=400, detail={"error_code": exc.error_code, "message": exc.message}
        ) from exc
    except GripperProduceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "SQS_PRODUCE_FAILED",
                "message": "로봇에 그리퍼 명령을 전달하지 못했습니다. 운영자 확인이 필요합니다.",
            },
        ) from exc
    return TeachingPendantGripperAccepted(gripper_cmd_id=gripper_cmd_id)


@router.post("/stop", response_model=TeachingPendantStopOut)
async def request_stop() -> TeachingPendantStopOut:
    try:
        result = await TeachingPendantService.request_stop()
    except SessionInactiveError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "SESSION_INACTIVE", "message": "조그 세션이 비활성 상태입니다"},
        ) from exc
    return TeachingPendantStopOut(**result)
