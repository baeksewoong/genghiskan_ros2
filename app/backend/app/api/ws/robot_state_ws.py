import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.events import broadcast_ephemeral
from app.services.robot_state_service import RobotStateService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/robot-state")
async def robot_state_websocket(
    websocket: WebSocket, token: str | None = Query(default=None)
) -> None:
    """ROS2 쪽 브릿지가 실물 로봇의 조인트 각도를 올리는 전용 피드.

    쓰기 경로(외부에서 메시지를 주입)라 토큰 인증을 accept 전에 수행한다 —
    미설정/불일치면 handshake 자체를 거부한다(fail-closed). 인증 통과한
    메시지는 검증 후 broadcast_ephemeral로 /ws/client 연결에만 바로
    전파하고, DB(event_logs)에는 기록하지 않는다(10Hz 안팎으로 계속
    들어오는 피드라 매번 insert하면 테이블이 터진다).
    """
    if not RobotStateService.is_token_valid(token):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("robot-state: invalid JSON dropped: %.200r", raw)
                continue

            if not RobotStateService.is_valid_joint_payload(payload):
                logger.warning("robot-state: invalid payload dropped: %.200r", payload)
                continue

            await broadcast_ephemeral("robot.joints_updated", payload)
    except WebSocketDisconnect:
        pass
