import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def test_health_and_state():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"db": True}

        state = client.get("/api/state")
        assert state.status_code == 200
        snapshot = state.json()
        assert snapshot["printers"][0]["slot"] == 1
        assert "robot" not in snapshot and "simulator" not in snapshot

        assert client.post("/api/orders", json={"shape": "TRIANGLE"}).status_code == 405  # 수동 주문 경로 제거됨
        assert client.get("/api/simulator").status_code == 404

        receive = client.get("/api/receive-pos")
        assert receive.status_code == 200
        assert [r["pos_id"] for r in receive.json()] == [1, 2]
