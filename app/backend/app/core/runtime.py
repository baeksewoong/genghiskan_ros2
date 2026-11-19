import asyncio
import time
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class TeachingPendantSession:
    """티칭 팬던트(실물 로봇 조그 제어) 세션의 런타임 상태 (PRD:
    assets/docs/prd-teaching-pendant.md 5장) — DB에 영속화하지 않는다. 서버가
    재시작되면 항상 비활성 상태로 시작한다 (로봇의 중간 상태가 애매해지는 것을
    막기 위해 일부러 복원하지 않는 설계 결정).

    상호 배제 대상은 실물 로봇 작업요청(WorkRequestService) 경로다 (PRD 3장)."""

    enabled: bool = False
    # 로그인이 없는 현재 구조에서 "한 번에 한 명만 조그"를 식별하는 단순 락 용도.
    # 지금은 임의 문자열/None 이상의 의미는 두지 않는다 (PRD 10장 미결).
    owner: str | None = None
    current_pose: dict | None = None  # {"space": "TASK"|"JOINT", "posx": [...]}
    gripper_state: str | None = None  # "OPEN" | "CLOSE" | None(아직 모름)

    # PRD 8.2 "스텝 상호 배제" — 이전 스텝의 완료/실패 응답을 받기 전까지는 새
    # 조그/그리퍼 요청을 받지 않는다. 조그와 그리퍼는 한 조그 세션 안에서 항상
    # 순서대로 하나씩만 진행되므로(PRD 7장 — SQS MessageGroupId도 "jog"로 공유)
    # pending 필드도 조그/그리퍼가 공유한다.
    pending_jog_id: str | None = None
    pending_gripper_cmd_id: str | None = None
    pending_since_monotonic: float | None = None  # TP-11 타임아웃 판정용

    def has_pending(self) -> bool:
        return self.pending_jog_id is not None or self.pending_gripper_cmd_id is not None

    def clear_pending(self) -> None:
        self.pending_jog_id = None
        self.pending_gripper_cmd_id = None
        self.pending_since_monotonic = None


@dataclass
class RuntimeState:
    """서버 프로세스 메모리에만 두는 런타임 상태.

    DB가 단일 진실 원천인 주문·프린터·재고와 달리, 이 값들은 재시작 시
    초기화돼도 무방하다 (웹 소켓 핸들, 티칭 팬던트 세션).
    """

    client_connections: set[WebSocket] = field(default_factory=set)

    teaching_pendant: TeachingPendantSession = field(default_factory=TeachingPendantSession)
    teaching_pendant_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # alert.receive_pos_full을 이미 보낸 work_id 집합 — 타이머 스윕(0.5초 간격)이
    # 수령대가 비기 전까지 매 틱마다 같은 조건을 다시 발견해도, 한 번 알린 work_id는
    # alert.receive_pos_full_cleared가 날 때까지 다시 보내지 않기 위한 용도다.
    # 재시작되면 비워져도 무방하다 — 조건이 여전하면 다음 스윕에서 한 번 더 알리면 된다.
    receive_pos_full_alerted_work_ids: set[int] = field(default_factory=set)


runtime = RuntimeState()
