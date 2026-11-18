import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.sqs_producer_service import SqsProducerService

pytestmark = pytest.mark.asyncio


async def test_session_enable_disable_roundtrip(monkeypatch):
    with TestClient(app) as client:
        enabled = client.post("/api/teaching-pendant/session", json={"enable": True})
        assert enabled.status_code == 200
        assert enabled.json() == {"enabled": True, "current_pose": None}

        disabled = client.post("/api/teaching-pendant/session", json={"enable": False})
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False


async def test_session_enable_rejected_when_robot_busy(monkeypatch):
    async def fake_produce(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(SqsProducerService, "produce_load_command", fake_produce)

    with TestClient(app) as client:
        board = client.post("/api/board-stock/refill-complete")
        assert board.status_code == 200

        created = client.post("/api/work-requests", json={"shape": "STAR"})
        assert created.status_code == 201
        assert created.json()["status"] == "DISPATCHING"

        resp = client.post("/api/teaching-pendant/session", json={"enable": True})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "ROBOT_BUSY"


async def test_jog_flow_and_step_pending_rejection(monkeypatch):
    async def fake_jog(**kwargs) -> bool:
        return True

    monkeypatch.setattr(SqsProducerService, "produce_jog_command", fake_jog)

    with TestClient(app) as client:
        assert client.post("/api/teaching-pendant/session", json={"enable": True}).status_code == 200

        first = client.post(
            "/api/teaching-pendant/jog",
            json={"space": "TASK", "ref_frame": "BASE", "axis": "X", "direction": 1, "step_size": 5},
        )
        assert first.status_code == 202
        jog_id = first.json()["jog_id"]
        assert jog_id

        second = client.post(
            "/api/teaching-pendant/jog",
            json={"space": "TASK", "ref_frame": "BASE", "axis": "Y", "direction": 1, "step_size": 5},
        )
        assert second.status_code == 409
        assert second.json()["detail"]["error_code"] == "STEP_PENDING"


async def test_jog_rejected_when_session_inactive():
    with TestClient(app) as client:
        resp = client.post(
            "/api/teaching-pendant/jog",
            json={"space": "TASK", "ref_frame": "BASE", "axis": "X", "direction": 1, "step_size": 5},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "SESSION_INACTIVE"


async def test_jog_step_size_over_limit_returns_400():
    with TestClient(app) as client:
        assert client.post("/api/teaching-pendant/session", json={"enable": True}).status_code == 200

        resp = client.post(
            "/api/teaching-pendant/jog",
            json={"space": "TASK", "ref_frame": "BASE", "axis": "X", "direction": 1, "step_size": 999},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "STEP_SIZE_EXCEEDED"


async def test_gripper_flow(monkeypatch):
    async def fake_gripper(**kwargs) -> bool:
        return True

    monkeypatch.setattr(SqsProducerService, "produce_gripper_command", fake_gripper)

    with TestClient(app) as client:
        assert client.post("/api/teaching-pendant/session", json={"enable": True}).status_code == 200

        resp = client.post("/api/teaching-pendant/gripper", json={"action": "OPEN"})
        assert resp.status_code == 202
        assert resp.json()["gripper_cmd_id"]


async def test_stop_endpoint_requires_active_session():
    with TestClient(app) as client:
        inactive = client.post("/api/teaching-pendant/stop")
        assert inactive.status_code == 409

        assert client.post("/api/teaching-pendant/session", json={"enable": True}).status_code == 200
        active = client.post("/api/teaching-pendant/stop")
        assert active.status_code == 200
        assert active.json()["ok"] is True
