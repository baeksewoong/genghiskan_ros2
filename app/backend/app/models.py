from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.enums import (
    ACTIVE_TASK_STATUSES,
    SHAPE_PRINT_DURATION_SEC,
    BoardStockStatus,
    EventDirection,
    OrderSource,
    OrderStatus,
    PrinterStatus,
    Shape,
    TaskStatus,
    TaskType,
)

# SQLite는 ROWID 별칭(AUTOINCREMENT)으로 쓰려면 정확히 INTEGER 타입이 필요하다.
# 운영 DB(MySQL)에서는 그대로 BIGINT를 쓰고, 테스트용 SQLite에서만 INTEGER로 내린다.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class InvalidStateTransitionError(Exception):
    """엔티티가 현재 상태에서 허용되지 않는 전이를 시도했을 때(Domain 불변식 위반).

    Application 계층(서비스)은 호출 전에 쿼리로 이미 전제 조건을 걸러두는 경우가
    많아 정상 흐름에서는 발생하지 않는다 — 발생한다면 레포지토리 조회 조건과
    엔티티 전이 규칙이 어긋났다는 뜻이다. 사용자 대상 에러로 바꿔야 하는 경우
    (예: OrderService.pick_up)는 서비스가 이 예외를 잡아 자신의 도메인 예외로
    다시 던진다."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_status_created_at", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    shape: Mapped[Shape] = mapped_column(SAEnum(Shape, native_enum=True, length=16))
    print_duration_sec: Mapped[int] = mapped_column(Integer)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, native_enum=True, length=20), default=OrderStatus.WAITING
    )
    source: Mapped[OrderSource] = mapped_column(SAEnum(OrderSource, native_enum=True, length=12))
    printer_slot: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    print_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    pickup_delay_sec: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))

    # ---- 생성 ----

    @classmethod
    def create_new(cls, *, user_id: int, shape: Shape, source: OrderSource, now: datetime) -> "Order":
        """새 주문을 WAITING 상태로 만든다. 모양→출력시간 매핑(SHAPE_PRINT_DURATION_SEC)은
        주문 자체의 불변식이므로 엔티티가 책임진다."""
        return cls(
            user_id=user_id,
            shape=shape,
            print_duration_sec=SHAPE_PRINT_DURATION_SEC[shape],
            status=OrderStatus.WAITING,
            source=source,
            created_at=now,
            updated_at=now,
        )

    # ---- 상태 전이 ----

    def mark_dispatching(self, now: datetime) -> None:
        """작업요청(SQS) 경로 전용: LOAD 명령 발행 성공 ~ success_load1 수신 전까지
        ("투입중")."""
        self._ensure_status((OrderStatus.WAITING,), "dispatching으로 전이")
        self.status = OrderStatus.DISPATCHING
        self.updated_at = now

    def mark_loading(self, now: datetime, printer_slot: int | None = None) -> None:
        """가상 로봇 경로(WAITING→LOADING, 프린터가 이미 확정됨)와 작업요청 경로
        (DISPATCHING→LOADING, success_load1 수신 시점 — 프린터는 아직 모름) 둘 다
        이 메서드로 전이한다."""
        self._ensure_status((OrderStatus.WAITING, OrderStatus.DISPATCHING), "loading으로 전이")
        self.status = OrderStatus.LOADING
        if printer_slot is not None:
            self.printer_slot = printer_slot
        self.updated_at = now

    def assign_printer(self, slot: int, now: datetime) -> None:
        """작업요청(SQS) 경로 전용: success_load1 이후 그 시점에 비어있는 프린터를
        찾아 확정한다 (상태 전이는 아니고 배정만)."""
        self.printer_slot = slot
        self.updated_at = now

    def mark_printing(self, now: datetime) -> None:
        self._ensure_status((OrderStatus.LOADING,), "printing으로 전이")
        self.status = OrderStatus.PRINTING
        self.started_at = now
        self.updated_at = now

    def mark_print_done(self, now: datetime) -> None:
        self._ensure_status((OrderStatus.PRINTING,), "print_done으로 전이")
        self.status = OrderStatus.PRINT_DONE
        self.print_completed_at = now
        self.updated_at = now

    def mark_unloading(self, now: datetime) -> None:
        self._ensure_status((OrderStatus.PRINT_DONE,), "unloading으로 전이")
        self.status = OrderStatus.UNLOADING
        self.updated_at = now

    def mark_ready_for_pickup(self, now: datetime) -> None:
        self._ensure_status((OrderStatus.UNLOADING,), "ready_for_pickup으로 전이")
        self.status = OrderStatus.READY_FOR_PICKUP
        self.ready_at = now
        self.updated_at = now

    def mark_picked_up(self, now: datetime) -> None:
        """수령대에서 "수령하기"를 눌렀을 때만 전이한다 — pickup_delay_sec이 지나도
        자동으로 전이되지 않는다."""
        self._ensure_status((OrderStatus.READY_FOR_PICKUP,), "picked_up으로 전이")
        self.status = OrderStatus.PICKED_UP
        self.picked_up_at = now
        self.updated_at = now

    def revert_to_waiting(self, now: datetime) -> None:
        """LOAD 작업이 취소/거부/실패(NO_BOARD)됐을 때 디스패치 이전 상태로 되돌린다."""
        self._ensure_status((OrderStatus.LOADING,), "waiting으로 복귀")
        self.status = OrderStatus.WAITING
        self.printer_slot = None
        self.updated_at = now

    def revert_to_print_done(self, now: datetime) -> None:
        """UNLOAD 작업이 취소/거부됐을 때 디스패치 이전 상태로 되돌린다."""
        self._ensure_status((OrderStatus.UNLOADING,), "print_done으로 복귀")
        self.status = OrderStatus.PRINT_DONE
        self.updated_at = now

    def touch(self, now: datetime) -> None:
        """상태 전이 없이 갱신 시각만 bump한다 (예: GRIP_FAIL 등으로 현재 단계에
        머무른 채 운영자 확인을 기다릴 때)."""
        self.updated_at = now

    def _ensure_status(self, allowed: tuple[OrderStatus, ...], action: str) -> None:
        if self.status not in allowed:
            raise InvalidStateTransitionError(
                f"order {self.id}는 현재 상태({self.status})에서 '{action}'을 할 수 없습니다"
            )


class Printer(Base):
    __tablename__ = "printers"

    slot: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    status: Mapped[PrinterStatus] = mapped_column(
        SAEnum(PrinterStatus, native_enum=True, length=16), default=PrinterStatus.EMPTY
    )
    current_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id"), nullable=True
    )
    timer_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))

    def reserve(self, order_id: int, now: datetime) -> None:
        """빈 프린터를 특정 주문에 배정한다. 가상 로봇 경로의 LOAD 예약과 작업요청
        경로의 배치 명령(success_load1 이후) 둘 다 이 메서드를 쓴다."""
        self._ensure_status((PrinterStatus.EMPTY,), "reserve")
        self.status = PrinterStatus.RESERVED
        self.current_order_id = order_id
        self.updated_at = now

    def start_unloading(self, now: datetime) -> None:
        self._ensure_status((PrinterStatus.DONE,), "unloading 시작")
        self.status = PrinterStatus.UNLOADING
        self.updated_at = now

    def start_printing(self, now: datetime, timer_ends_at: datetime) -> None:
        self._ensure_status((PrinterStatus.RESERVED,), "printing 시작")
        self.status = PrinterStatus.PRINTING
        self.timer_ends_at = timer_ends_at
        self.updated_at = now

    def mark_done(self, now: datetime) -> None:
        """출력 타이머가 끝나 DONE으로 전이한다(TimerService의 출력 완료 스윕)."""
        self._ensure_status((PrinterStatus.PRINTING,), "done으로 전이(출력 완료)")
        self.status = PrinterStatus.DONE
        self.updated_at = now

    def revert_to_done(self, now: datetime) -> None:
        """UNLOAD 작업이 취소/거부됐을 때 (완성품은 그대로 있으므로) DONE으로
        되돌린다."""
        self._ensure_status((PrinterStatus.UNLOADING,), "done으로 복귀")
        self.status = PrinterStatus.DONE
        self.updated_at = now

    def clear(self, now: datetime) -> None:
        """비운다: LOAD 취소(RESERVED→EMPTY) 또는 UNLOAD 성공(UNLOADING→EMPTY) 둘
        다 이 메서드를 쓴다."""
        self._ensure_status((PrinterStatus.RESERVED, PrinterStatus.UNLOADING), "empty로 전이")
        self.status = PrinterStatus.EMPTY
        self.current_order_id = None
        self.updated_at = now

    def touch(self, now: datetime) -> None:
        self.updated_at = now

    def _ensure_status(self, allowed: tuple[PrinterStatus, ...], action: str) -> None:
        if self.status not in allowed:
            raise InvalidStateTransitionError(
                f"printer {self.slot}은 현재 상태({self.status})에서 '{action}'을 할 수 없습니다"
            )


class RobotTask(Base):
    __tablename__ = "robot_tasks"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"))
    type: Mapped[TaskType] = mapped_column(SAEnum(TaskType, native_enum=True, length=8))
    # 작업요청(SQS) 경로: dispatch 시점엔 프린터를 모른다 — success_load1 수신 시점에
    # 비로소 정해진다 (그 전까지는 NULL).
    printer_slot: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=True, length=16), default=TaskStatus.DISPATCHED
    )
    last_phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 작업요청(SQS) 경로 전용: LOAD 발행 시 보낸 body 값의 스냅샷 (PRD 5장).
    start_pos_id: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    sd_pos_id: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    # ---- 생성 (디스패치) ----

    @classmethod
    def dispatch_load(cls, *, order_id: int, printer_slot: int, now: datetime) -> "RobotTask":
        """가상 로봇(/ws/bridge) 경로: 목적지 프린터가 이미 정해진 LOAD 작업."""
        return cls(
            order_id=order_id,
            type=TaskType.LOAD,
            printer_slot=printer_slot,
            status=TaskStatus.DISPATCHED,
            dispatched_at=now,
        )

    @classmethod
    def dispatch_unload(cls, *, order_id: int, printer_slot: int, now: datetime) -> "RobotTask":
        """가상 로봇(/ws/bridge) 경로의 UNLOAD 작업."""
        return cls(
            order_id=order_id,
            type=TaskType.UNLOAD,
            printer_slot=printer_slot,
            status=TaskStatus.DISPATCHED,
            dispatched_at=now,
        )

    @classmethod
    def dispatch_load_request(cls, *, order_id: int, start_pos_id: int, now: datetime) -> "RobotTask":
        """작업요청(SQS) 경로: 목적지 프린터를 아직 모르는 채로 베드 집기(start_pos_id)만
        디스패치한다 — 프린터는 success_load1 수신 후 assign_printer로 확정한다."""
        return cls(
            order_id=order_id,
            type=TaskType.LOAD,
            printer_slot=None,
            status=TaskStatus.DISPATCHED,
            start_pos_id=start_pos_id,
            sd_pos_id=None,
            dispatched_at=now,
        )

    # ---- 상태 전이 ----

    def mark_running(self, now: datetime) -> None:
        self._ensure_status((TaskStatus.DISPATCHED,), "running으로 전이")
        self.status = TaskStatus.RUNNING
        self.started_at = self.started_at or now

    def mark_succeeded(self, now: datetime) -> None:
        self._ensure_status(ACTIVE_TASK_STATUSES, "succeeded로 전이")
        self.status = TaskStatus.SUCCEEDED
        self.finished_at = now

    def mark_failed(self, now: datetime, error_code: str | None) -> None:
        self._ensure_status(ACTIVE_TASK_STATUSES, "failed로 전이")
        self.status = TaskStatus.FAILED
        self.error_code = error_code
        self.finished_at = now

    def cancel(self, now: datetime, error_code: str | None = None) -> None:
        """로봇에 내려보냈지만 거부/연결끊김/전송실패 등으로 취소됐을 때."""
        self._ensure_status(ACTIVE_TASK_STATUSES, "cancel")
        self.status = TaskStatus.CANCELED
        if error_code is not None:
            self.error_code = error_code
        self.finished_at = now

    def record_feedback(self, phase: str | None) -> None:
        self.last_phase = phase

    def assign_printer(self, slot: int) -> None:
        """작업요청(SQS) 경로 전용: success_load1 이후 배치 명령(sd_pos_id)의
        목적지가 정해질 때 호출한다."""
        self.printer_slot = slot
        self.sd_pos_id = slot

    def _ensure_status(self, allowed: tuple[TaskStatus, ...], action: str) -> None:
        if self.status not in allowed:
            raise InvalidStateTransitionError(
                f"robot_task {self.id}는 현재 상태({self.status})에서 '{action}'을 할 수 없습니다"
            )


class BoardStock(Base):
    """적재대 층(1~3)별 베드 적재 상태 (PRD: assets/docs/prd-work-request-sqs.md 5장).
    로봇은 맨 위(슬롯 번호가 가장 큰 OCCUPIED 층)에서 집는다."""

    __tablename__ = "board_stock"

    slot: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    status: Mapped[BoardStockStatus] = mapped_column(
        SAEnum(BoardStockStatus, native_enum=True, length=16), default=BoardStockStatus.EMPTY
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))

    def reserve(self, now: datetime) -> None:
        """작업요청(SQS) 경로: dispatch 시점에 집을 베드를 예약한다."""
        self._ensure_status((BoardStockStatus.OCCUPIED,), "reserve")
        self.status = BoardStockStatus.RESERVED
        self.updated_at = now

    def release(self, now: datetime) -> None:
        """베드 집기 성공(success_load1) 시 비운다. 이미 RESERVED가 아니면(중복
        수신 등 레이스) 조용히 무시한다 — 기존 서비스 코드의 관용적 가드를 그대로
        옮긴 것이다."""
        if self.status == BoardStockStatus.RESERVED:
            self.status = BoardStockStatus.EMPTY
            self.updated_at = now

    def refill(self, now: datetime) -> None:
        """"채우기 완료" 버튼: 그 시점에 EMPTY인 층만 OCCUPIED로 바꾼다. 이미
        OCCUPIED/RESERVED인 층은 그대로 둔다."""
        if self.status == BoardStockStatus.EMPTY:
            self.status = BoardStockStatus.OCCUPIED
            self.updated_at = now

    def _ensure_status(self, allowed: tuple[BoardStockStatus, ...], action: str) -> None:
        if self.status not in allowed:
            raise InvalidStateTransitionError(
                f"board_stock {self.slot}은 현재 상태({self.status})에서 '{action}'을 할 수 없습니다"
            )


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    type: Mapped[str] = mapped_column(String(64))
    direction: Mapped[EventDirection] = mapped_column(SAEnum(EventDirection, native_enum=True, length=20))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
