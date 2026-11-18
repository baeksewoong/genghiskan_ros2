import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.sqs_producer_service import SqsProducerService

pytestmark = pytest.mark.asyncio


async def test_send_unload2_publishes_with_retry_token(monkeypatch):
    sent: list[dict] = []

    async def fake_unload2(*, work_id, receive_pos_id, retry_token=None):
        sent.append({"work_id": work_id, "receive_pos_id": receive_pos_id, "retry_token": retry_token})
        return True

    monkeypatch.setattr(SqsProducerService, "produce_unload2_command", fake_unload2)

    with TestClient(app) as client:
        resp = client.post("/api/sqs/commands/unload2", json={"work_id": 2, "receive_pos_id": 1})
        again = client.post("/api/sqs/commands/unload2", json={"work_id": 2, "receive_pos_id": 1})

    assert resp.status_code == 200
    assert resp.json() == {"sent": True, "body": {"type": "unload2", "work_id": 2, "receive_pos_id": 1}}
    assert again.status_code == 200
    # 같은 work_id로 다시 보내도 FIFO 중복 제거에 걸리지 않게 매번 다른 토큰을 쓴다.
    assert sent[0]["retry_token"] and sent[0]["retry_token"] != sent[1]["retry_token"]


@pytest.mark.parametrize("payload", [{"work_id": 2, "receive_pos_id": 3}, {"work_id": 0, "receive_pos_id": 1}, {"receive_pos_id": 1}])
async def test_send_unload2_rejects_invalid_body(payload):
    with TestClient(app) as client:
        resp = client.post("/api/sqs/commands/unload2", json=payload)
    assert resp.status_code == 422


async def test_send_unload2_returns_502_when_queue_not_configured():
    # 테스트 환경은 COMMAND_QUEUE_URL이 빈 값이라 실제 발행이 건너뛰어진다.
    with TestClient(app) as client:
        resp = client.post("/api/sqs/commands/unload2", json={"work_id": 2, "receive_pos_id": 2})
    assert resp.status_code == 502
    assert resp.json()["detail"]["error_code"] == "SQS_PRODUCE_FAILED"
