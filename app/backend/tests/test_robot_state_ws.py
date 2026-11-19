import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.main import app
from app.repositories.event_log_repository import EventLogRepository

pytestmark = pytest.mark.asyncio


async def test_robot_state_ws_rejects_when_token_unset(monkeypatch):
    monkeypatch.setattr(settings, "robot_state_ws_token", None)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/robot-state"):
                pass


async def test_robot_state_ws_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "robot_state_ws_token", "secret-token")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/robot-state?token=wrong"):
                pass


async def test_robot_state_ws_broadcasts_valid_payload_and_skips_invalid(monkeypatch):
    monkeypatch.setattr(settings, "robot_state_ws_token", "secret-token")
    valid_payload = {
        "robot_id": "robot-arm-1",
        "seq": 1,
        "timestamp_ms": 1700000000000,
        "angle_unit": "rad",
        "joints": {
            "joint_1": 0.0,
            "joint_2": 0.0,
            "joint_3": 1.57,
            "joint_4": 0.0,
            "joint_5": 1.57,
            "joint_6": 0.0,
        },
        "source": "ros2_sfarm_bridge",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/ws/client") as web_client:
            web_client.receive_json()  # state.snapshot

            with client.websocket_connect(
                "/ws/robot-state?token=secret-token"
            ) as robot_ws:
                # 검증 실패(비-finite 값) payload는 조용히 drop되고 연결은 유지된다.
                robot_ws.send_json(
                    {"angle_unit": "rad", "joints": {"joint_1": float("nan")}}
                )
                # angle_unit이 허용값이 아닌 경우도 drop된다.
                robot_ws.send_json({"angle_unit": "xyz", "joints": {"joint_1": 0.0}})

                robot_ws.send_json(valid_payload)
                envelope = web_client.receive_json()

        assert envelope["type"] == "robot.joints_updated"
        assert envelope["data"] == valid_payload
        assert "event_id" in envelope and "ts" in envelope

        # 이 피드는 DB(event_logs)에 영속화하지 않는다.
        async with AsyncSessionLocal() as session:
            logs = await EventLogRepository.list_by_type_prefix(
                session, "robot.joints_updated", limit=10
            )
        assert logs == []
