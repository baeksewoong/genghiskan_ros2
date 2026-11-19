"""서버 → 웹 메시지 봉투를 만들고 내보내는 인프라 계층.

비즈니스 로직(서비스 계층)은 이 모듈을 통해서만 WebSocket으로 이벤트를 내보내며,
실제 event_logs 테이블 기록은 레포지토리 계층(EventLogRepository)에 위임한다.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime import runtime
from app.repositories.event_log_repository import EventLogRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def make_envelope(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": event_type,
        "event_id": str(uuid.uuid4()),
        "ts": _now_iso(),
        "data": data,
    }


async def broadcast_to_web(session: AsyncSession, event_type: str, data: dict[str, Any]) -> None:
    envelope = make_envelope(event_type, data)
    EventLogRepository.add(session, envelope)
    dead: list = []
    for ws in runtime.client_connections:
        try:
            await ws.send_json(envelope)
        except Exception:
            dead.append(ws)
    for ws in dead:
        runtime.client_connections.discard(ws)


async def broadcast_ephemeral(event_type: str, data: dict[str, Any]) -> None:
    """DB(event_logs)에 기록하지 않고 /ws/client 연결에만 바로 보내는 경량 브로드캐스트.

    실물 로봇 조인트 각도 피드(/ws/robot-state)처럼 10Hz 안팎으로 계속 들어오는
    피드를 broadcast_to_web으로 그대로 흘리면 매 호출마다 event_logs에 insert가
    쌓여 테이블이 터진다. 이 피드는 "현재 값"만 의미가 있고 히스토리를 남길
    필요가 없으므로 DB 기록을 건너뛴다. 세션이 필요 없어 인자도 없다.
    """
    envelope = make_envelope(event_type, data)
    dead: list = []
    for ws in runtime.client_connections:
        try:
            await ws.send_json(envelope)
        except Exception:
            dead.append(ws)
    for ws in dead:
        runtime.client_connections.discard(ws)


async def send_envelope_to(
    session: AsyncSession, ws, event_type: str, data: dict[str, Any]
) -> None:
    envelope = make_envelope(event_type, data)
    EventLogRepository.add(session, envelope)
    await ws.send_json(envelope)
