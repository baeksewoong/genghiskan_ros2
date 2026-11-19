from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.enums import (
    ACTIVE_TASK_STATUSES,
    SHAPE_PRINT_DURATION_SEC,
    BoardStockStatus,
    OrderStatus,
    PrinterStatus,
    ReceivePosStatus,
    Shape,
    TaskStatus,
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
    printer_slot: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # 작업요청(SQS) 경로 전용: unload2로 완성품을 내려놓을 수령대 위치(1/2).
    receive_pos_id: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    print_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))

    # ---- 생성 ----

    @classmethod
    def create_new(cls, *, user_id: int, shape: Shape, now: datetime) -> "Order":
        """새 주문을 WAITING 상태로 만든다. 모양→출력시간 매핑(SHAPE_PRINT_DURATION_SEC)은
        주문 자체의 불변식이므로 엔티티가 책임진다."""
        return cls(
            user_id=user_id,
            shape=shape,
            print_duration_sec=SHAPE_PRINT_DURATION_SEC[shape],
            status=OrderStatus.WAITING,
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

    def mark_loading(self, now: datetime) -> None:
        """DISPATCHING→LOADING (success_load1 수신 시점 — 프린터는 아직 모름)."""
        self._ensure_status((OrderStatus.DISPATCHING,), "loading으로 전이")
        self.status = OrderStatus.LOADING
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

    def assign_receive_pos(self, receive_pos_id: int, now: datetime) -> None:
        """작업요청(SQS) 경로 전용: success_unload1 이후(UNLOADING) 비어있는 수령대를
        배정한다. 이 시점부터 해당 수령대는 점유된 것으로 본다. UNLOADING인데
        receive_pos_id가 없으면 "로봇이 완성품을 들고 수령대가 비길 기다리는 중"이다."""
        self._ensure_status((OrderStatus.UNLOADING,), "수령대 배정")
        self.receive_pos_id = receive_pos_id
        self.updated_at = now

    def mark_ready_for_pickup(self, now: datetime) -> None:
        self._ensure_status((OrderStatus.UNLOADING,), "ready_for_pickup으로 전이")
        self.status = OrderStatus.READY_FOR_PICKUP
        self.ready_at = now
        self.updated_at = now

    def mark_picked_up(self, now: datetime) -> None:
        """수령대에서 "수령하기"를 눌렀을 때만 전이한다."""
        self._ensure_status((OrderStatus.READY_FOR_PICKUP,), "picked_up으로 전이")
        self.status = OrderStatus.PICKED_UP
        self.picked_up_at = now
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
        """빈 프린터를 특정 주문에 배정한다 (success_load1 이후 배치 명령 시점)."""
        self._ensure_status((PrinterStatus.EMPTY,), "reserve")
        self.status = PrinterStatus.RESERVED
        self.current_order_id = order_id
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

    def release_after_unload(self, now: datetime) -> None:
        """작업요청(SQS) 경로 전용: success_unload1(완성품 꺼내기 성공) 시 DONE→EMPTY."""
        self._ensure_status((PrinterStatus.DONE,), "unload1 후 비우기")
        self.status = PrinterStatus.EMPTY
        self.current_order_id = None
        self.timer_ends_at = None
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
    # 작업요청(SQS) 경로: dispatch 시점엔 프린터를 모른다 — success_load1 수신 시점에
    # 비로소 정해진다 (그 전까지는 NULL).
    printer_slot: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=True, length=16), default=TaskStatus.DISPATCHED
    )
    # 작업요청(SQS) 경로 전용: LOAD 발행 시 보낸 body 값의 스냅샷 (PRD 5장).
    start_pos_id: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    sd_pos_id: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    # ---- 생성 (디스패치) ----

    @classmethod
    def dispatch_load_request(cls, *, order_id: int, start_pos_id: int, now: datetime) -> "RobotTask":
        """작업요청(SQS) 경로: 목적지 프린터를 아직 모르는 채로 베드 집기(start_pos_id)만
        디스패치한다 — 프린터는 success_load1 수신 후 assign_printer로 확정한다."""
        return cls(
            order_id=order_id,
            printer_slot=None,
            status=TaskStatus.DISPATCHED,
            start_pos_id=start_pos_id,
            sd_pos_id=None,
            dispatched_at=now,
        )

    @classmethod
    def dispatch_unload_request(cls, *, order_id: int, printer_slot: int, now: datetime) -> "RobotTask":
        """작업요청(SQS) 경로: unload1(완성품 꺼내기) 디스패치 시점에 생성한다. 꺼낼
        프린터(printer_slot/sd_pos_id)는 이미 알고 있다 — LOAD와 반대로 목적지(수령대)를
        아직 모르는 채로 시작한다. 이 행이 LOAD 행과 같은 방식(DISPATCHED/RUNNING인
        동안 "활성")으로 로봇 점유 상태를 나타내, unload1~unload2 사이에 다른 작업이
        끼어들지 못하게 막는다 (get_active_real_robot_task_locked 참고)."""
        return cls(
            order_id=order_id,
            printer_slot=printer_slot,
            status=TaskStatus.DISPATCHED,
            start_pos_id=None,
            sd_pos_id=printer_slot,
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


class ReceivePos(Base):
    """수령대(1, 2)별 현황. 작업요청(SQS) 경로의 unload2 목적지를 고르는 기준이다.
    EMPTY → RESERVED(unload2 발행) → OCCUPIED(success_unload2) → EMPTY(수령하기)."""

    __tablename__ = "receive_pos"

    pos_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    status: Mapped[ReceivePosStatus] = mapped_column(
        SAEnum(ReceivePosStatus, native_enum=True, length=16), default=ReceivePosStatus.EMPTY
    )
    current_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))

    def reserve(self, order_id: int, now: datetime) -> None:
        """unload2 발행 시점: 로봇이 이 수령대로 완성품을 가져오는 중."""
        self._ensure_status((ReceivePosStatus.EMPTY,), "reserve")
        self.status = ReceivePosStatus.RESERVED
        self.current_order_id = order_id
        self.updated_at = now

    def occupy(self, now: datetime) -> None:
        """success_unload2: 완성품이 수령대에 놓였다."""
        self._ensure_status((ReceivePosStatus.RESERVED,), "occupy")
        self.status = ReceivePosStatus.OCCUPIED
        self.updated_at = now

    def release(self, now: datetime) -> None:
        """수령하기: 손님이 완성품을 가져갔다. 이미 EMPTY면 조용히 무시한다."""
        if self.status == ReceivePosStatus.EMPTY:
            return
        self.status = ReceivePosStatus.EMPTY
        self.current_order_id = None
        self.updated_at = now

    def _ensure_status(self, allowed: tuple[ReceivePosStatus, ...], action: str) -> None:
        if self.status not in allowed:
            raise InvalidStateTransitionError(
                f"receive_pos {self.pos_id}은 현재 상태({self.status})에서 '{action}'을 할 수 없습니다"
            )


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
