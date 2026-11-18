from enum import Enum


class Shape(str, Enum):
    TRIANGLE = "TRIANGLE"
    SQUARE = "SQUARE"
    STAR = "STAR"
    CIRCLE = "CIRCLE"


SHAPE_PRINT_DURATION_SEC: dict[Shape, int] = {
    Shape.TRIANGLE: 30,
    Shape.SQUARE: 40,
    Shape.STAR: 50,
    Shape.CIRCLE: 70,
}


class OrderStatus(str, Enum):
    WAITING = "WAITING"
    # 작업요청(SQS) 경로 전용: LOAD 명령 발행 성공 ~ success_load1 수신 전까지 ("투입중").
    # PRD: assets/docs/prd-work-request-sqs.md 5장.
    DISPATCHING = "DISPATCHING"
    LOADING = "LOADING"
    PRINTING = "PRINTING"
    PRINT_DONE = "PRINT_DONE"
    UNLOADING = "UNLOADING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"


class PrinterStatus(str, Enum):
    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    PRINTING = "PRINTING"
    DONE = "DONE"


class TaskStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


ACTIVE_TASK_STATUSES = (TaskStatus.DISPATCHED, TaskStatus.RUNNING)
ACTIVE_ORDER_STATUSES = (OrderStatus.LOADING, OrderStatus.PRINTING, OrderStatus.PRINT_DONE, OrderStatus.UNLOADING)


class AlertReason(str, Enum):
    # 작업요청(SQS) 경로 전용 (PRD: assets/docs/prd-work-request-sqs.md 5장 "채우기 완료" 버튼).
    BOARD_STOCK_EMPTY = "BOARD_STOCK_EMPTY"
    # robot-events에서 베드 집기 실패 이벤트(예: {"work_id":1,"type":"fail_load1"})를 받았을 때.
    LOAD_PICK_FAILED = "LOAD_PICK_FAILED"
    # robot-events에서 프린터 완성품 집기 실패 이벤트({"work_id":1,"type":"fail_unload1"})를 받았을 때.
    UNLOAD_PICK_FAILED = "UNLOAD_PICK_FAILED"
    # success_unload1 후 수령대(1, 2)가 모두 차 있어 unload2를 보내지 못했을 때.
    RECEIVE_POS_FULL = "RECEIVE_POS_FULL"


class BoardStockStatus(str, Enum):
    """적재대 층(1~3)별 상태 (PRD: assets/docs/prd-work-request-sqs.md 5장)."""

    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"


class ReceivePosStatus(str, Enum):
    """수령대(1, 2)별 상태. EMPTY → RESERVED(unload2 발행, 로봇이 가져오는 중) →
    OCCUPIED(success_unload2, 완성품 놓임) → EMPTY(수령하기)."""

    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"


# ---- 티칭 팬던트(실물 로봇 조그 제어) 전용 값 객체 ----
# (PRD: assets/docs/prd-teaching-pendant.md 5장) DB에 영속화하지 않는다 — 조그
# 세션은 서버 런타임 상태(app.core.runtime)로만 관리하므로, 이 enum들도 런타임
# 상태/SQS 메시지/API 스키마에서만 쓰는 값 객체다.


class JogSpace(str, Enum):
    TASK = "TASK"
    JOINT = "JOINT"


class JogRefFrame(str, Enum):
    """TASK 모드일 때만 쓰는 기준 좌표계. JOINT 모드에는 해당 없음."""

    BASE = "BASE"
    TOOL = "TOOL"


class GripperAction(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
