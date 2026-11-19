"""실물 로봇 조인트 각도 실시간 피드(/ws/robot-state) 전용 애플리케이션 서비스.

ROS2 쪽 브릿지가 WebSocket으로 보내는 조인트 각도를 그대로 웹 대시보드에
전파하기 위한 인증/페이로드 검증만 담당한다. 이 경로는 DB에 아무것도
영속화하지 않는다(런타임 브로드캐스트만, app.core.events.broadcast_ephemeral).

가상 로봇(/ws/bridge) 경로나 작업요청(SQS) 경로와는 완전히 무관한 별도 피드다 —
로봇의 "현재 보여줄 자세"만 알려주는 관측용 채널이라 OrderSource 구분과도
섞이지 않는다.
"""

import math
from numbers import Real
from typing import Any

from app.core.config import settings

_VALID_ANGLE_UNITS = {"rad", "deg"}


class RobotStateService:
    @staticmethod
    def is_token_valid(token: str | None) -> bool:
        """토큰 인증. settings.robot_state_ws_token이 비어있으면(미설정) 항상
        거부한다 — 이 엔드포인트는 외부에 노출될 수 있는 쓰기 경로라 안전
        기본값이 "거부"여야 한다(event_queue_url류의 "비어있으면 기능 끔"과 다름)."""
        configured = settings.robot_state_ws_token
        if not configured:
            return False
        return token == configured

    @staticmethod
    def is_valid_joint_payload(payload: Any) -> bool:
        """최소 검증: joints가 dict이고 모든 값이 finite number이며,
        angle_unit이 "rad"|"deg" 인지만 확인한다. 그 외 필드(robot_id, seq,
        timestamp_ms, source 등)는 그대로 통과시켜 ROS2 쪽 페이로드를
        래핑 없이 그대로 전파한다."""
        if not isinstance(payload, dict):
            return False

        if payload.get("angle_unit") not in _VALID_ANGLE_UNITS:
            return False

        joints = payload.get("joints")
        if not isinstance(joints, dict):
            return False

        for value in joints.values():
            # bool은 Real의 서브타입이라 별도로 걸러낸다.
            if isinstance(value, bool) or not isinstance(value, Real):
                return False
            if not math.isfinite(float(value)):
                return False

        return True
