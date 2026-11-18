from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums import (
    AlertReason,
    BoardStockStatus,
    ReceivePosStatus,
    GripperAction,
    JogRefFrame,
    JogSpace,
    OrderStatus,
    PrinterStatus,
    Shape,
)


class OrderCreateRequest(BaseModel):
    shape: Shape | None = None
    customer_name: str | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    # 수령대/대기열 UI 표시용 — 주문자(User)의 이름.
    customer_name: str | None = None
    shape: Shape
    print_duration_sec: int
    status: OrderStatus
    printer_slot: int | None
    receive_pos_id: int | None = None
    created_at: datetime
    started_at: datetime | None
    print_completed_at: datetime | None
    ready_at: datetime | None
    picked_up_at: datetime | None
    updated_at: datetime


class PrinterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slot: int
    status: PrinterStatus
    current_order_id: int | None
    # 작업대 현황 UI 표시용 — current_order_id가 있을 때 그 주문의 손님 이름.
    customer_name: str | None = None
    timer_ends_at: datetime | None
    updated_at: datetime


class BoardStockOut(BaseModel):
    """적재대 층(1~3)별 상태 (PRD: assets/docs/prd-work-request-sqs.md 5장)."""

    model_config = ConfigDict(from_attributes=True)

    slot: int
    status: BoardStockStatus
    updated_at: datetime


class ReceivePosOut(BaseModel):
    """수령대(1, 2)별 현황."""

    model_config = ConfigDict(from_attributes=True)

    pos_id: int
    status: ReceivePosStatus
    current_order_id: int | None
    updated_at: datetime


class Unload2CommandRequest(BaseModel):
    """unload2 SQS 수동 발행 (테스트/ROS 2 연동 확인용)."""

    work_id: int = Field(ge=1)
    receive_pos_id: Literal[1, 2]


class Unload2CommandOut(BaseModel):
    sent: bool
    body: dict


class StateSnapshot(BaseModel):
    printers: list[PrinterOut]
    waiting_orders: list[OrderOut]
    active_orders: list[OrderOut]
    pickup_orders: list[OrderOut]


class StatsOut(BaseModel):
    picked_up_count: int
    avg_wait_sec: float | None
    avg_print_sec: float | None
    avg_pickup_wait_sec: float | None


class HealthOut(BaseModel):
    db: bool


# ---- 티칭 팬던트(실물 로봇 조그 제어) ----
# PRD: assets/docs/prd-teaching-pendant.md 6장. 도메인 엔티티가 없는(DB 영속화 없음)
# 기능이라 이 스키마들은 서비스가 다루는 런타임 상태 dict를 응답 DTO로 좁혀 담는다.


class TeachingPendantSessionRequest(BaseModel):
    enable: bool


class TeachingPendantSessionOut(BaseModel):
    enabled: bool
    current_pose: dict | None = None


class TeachingPendantJogRequest(BaseModel):
    space: JogSpace
    # TASK 모드일 때만 필요 (JOINT는 기준 좌표계 개념이 없음) — 서비스 계층에서
    # space/axis 조합을 검증한다(PRD 9장 스텝 상한 포함).
    ref_frame: JogRefFrame | None = None
    axis: str
    direction: int
    step_size: float


class TeachingPendantJogAccepted(BaseModel):
    jog_id: str


class TeachingPendantGripperRequest(BaseModel):
    action: GripperAction


class TeachingPendantGripperAccepted(BaseModel):
    gripper_cmd_id: str


class TeachingPendantStopOut(BaseModel):
    ok: bool
    message: str
