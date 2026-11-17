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


class OrderSource(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    # 작업요청(SQS) 경로 전용 (WorkRequestService). 가상 로봇(/ws/bridge) 경로의
    # DispatcherService가 이 주문을 주워가지 않도록 MANUAL과 구분한다 — 그렇지 않으면
    # board_stock이 비어 WAITING으로 남은 작업요청 주문을, 가상 로봇 DispatcherService가
    # (board 체크 없이) 빈 프린터만 보고 멋대로 집어가 가상 로봇으로 완료시켜 버린다.
    WORK_REQUEST = "WORK_REQUEST"


class PrinterStatus(str, Enum):
    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    PRINTING = "PRINTING"
    DONE = "DONE"
    UNLOADING = "UNLOADING"


class TaskType(str, Enum):
    LOAD = "LOAD"
    UNLOAD = "UNLOAD"


class TaskStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


ACTIVE_TASK_STATUSES = (TaskStatus.DISPATCHED, TaskStatus.RUNNING)
ACTIVE_ORDER_STATUSES = (OrderStatus.LOADING, OrderStatus.PRINTING, OrderStatus.PRINT_DONE, OrderStatus.UNLOADING)


class RobotState(str, Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


class EventDirection(str, Enum):
    SERVER_TO_WEB = "SERVER_TO_WEB"
    SERVER_TO_BRIDGE = "SERVER_TO_BRIDGE"
    BRIDGE_TO_SERVER = "BRIDGE_TO_SERVER"


class AlertReason(str, Enum):
    # 작업요청(SQS) 경로 전용 (PRD: assets/docs/prd-work-request-sqs.md 5장 "채우기 완료" 버튼).
    BOARD_STOCK_EMPTY = "BOARD_STOCK_EMPTY"
    # robot-events에서 베드 집기 실패 이벤트(예: {"work_id":1,"type":"fail_load1"})를 받았을 때.
    LOAD_PICK_FAILED = "LOAD_PICK_FAILED"


class BoardStockStatus(str, Enum):
    """적재대 층(1~3)별 상태 (PRD: assets/docs/prd-work-request-sqs.md 5장)."""

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
