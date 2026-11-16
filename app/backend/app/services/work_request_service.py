"""작업요청(SQS 디스패치) 1건 처리. 기존 가상 로봇 경로(OrderService,
DispatcherService, board_inventory)와는 완전히 분리된 신규 경로다
(PRD: assets/docs/prd-work-request-sqs.md). 이 경로는 요청 하나를 받을 때마다
그 자리에서 즉시 베드를 확인해 판정한다 — 기존 DispatcherService처럼 로봇이
IDLE이 될 때마다 재평가하는 루프가 아니다.

LOAD는 두 단계다: dispatch 시점엔 베드(start_pos_id)만 확인해서 집기 명령을 보내고,
프린터는 아직 고르지 않는다. 로봇이 베드 집기에 성공(success_load1)했다고 보고하면
그때 비어있는 프린터를 찾아 배치 명령(sd_pos_id)을 보낸다 — dispatch와 배치 사이에
프린터 가용성이 바뀔 수 있어서, 더 정확한 시점에 고르기 위함."""

import logging
import random
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.events import broadcast_to_web
from app.enums import (
    SHAPE_PRINT_DURATION_SEC,
    AlertReason,
    BoardStockStatus,
    OrderSource,
    OrderStatus,
    PrinterStatus,
    Shape,
    TaskStatus,
    TaskType,
)
from app.models import Order, RobotTask
from app.repositories.board_stock_repository import BoardStockRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.printer_repository import PrinterRepository
from app.repositories.robot_task_repository import RobotTaskRepository
from app.repositories.user_repository import UserRepository
from app.schemas import OrderOut, PrinterOut
from app.services.sqs_producer_service import SqsProducerService

logger = logging.getLogger(__name__)

_SHAPE_CHOICES = list(Shape)


class BoardEmptyError(Exception):
    """적재대에 베드가 비어있어 작업요청을 디스패치할 수 없을 때. 주문 행 자체는
    이미 WAITING으로 저장돼 있다 (PRD 3장 2단계)."""

    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"board empty for order {order_id}")


class SqsProduceError(Exception):
    """SQS robot-commands 전송에 실패해 작업요청을 디스패치하지 못했을 때
    (PRD 3장 4단계 — 트랜잭션은 이미 롤백된 상태)."""

    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"SQS produce failed for order {order_id}")


class LoadRetryNotFoundError(Exception):
    """베드 집기 실패 알럿에서 "확인"을 눌렀는데, 재시도할 활성 LOAD 작업을
    찾을 수 없을 때(알 수 없는 work_id, 이미 다른 상태로 진행됨 등)."""

    def __init__(self, work_id: int):
        self.work_id = work_id
        super().__init__(f"no active LOAD task to retry for work_id {work_id}")


class WorkRequestService:
    @staticmethod
    async def create(
        session: AsyncSession,
        shape: Shape | None,
        customer_name: str | None = None,
    ) -> Order:
        order = await WorkRequestService._insert_order(session, shape, customer_name)

        async with AsyncSessionLocal() as session2:
            board = await BoardStockRepository.top_occupied_locked(session2)
            if board is None:
                await broadcast_to_web(
                    session2, "alert.refill_required", {"reason": AlertReason.BOARD_STOCK_EMPTY.value}
                )
                await session2.commit()
                raise BoardEmptyError(order.id)

            now = datetime.utcnow()
            board.status = BoardStockStatus.RESERVED
            board.updated_at = now

            task = RobotTask(
                order_id=order.id,
                type=TaskType.LOAD,
                printer_slot=None,
                status=TaskStatus.DISPATCHED,
                start_pos_id=board.slot,
                sd_pos_id=None,
                dispatched_at=now,
            )
            RobotTaskRepository.add(session2, task)

            order_db = await OrderRepository.get_locked(session2, order.id)
            order_db.status = OrderStatus.DISPATCHING
            order_db.updated_at = now
            await session2.flush()

            produced = await SqsProducerService.produce_load_command(work_id=order.id, start_pos_id=board.slot)
            if not produced:
                await session2.rollback()
                raise SqsProduceError(order.id)

            await broadcast_to_web(
                session2, "order.updated", OrderOut.model_validate(order_db).model_dump(mode="json")
            )
            await broadcast_to_web(
                session2, "board_stock.updated", await WorkRequestService._board_stock_snapshot(session2)
            )
            await session2.commit()
            return order_db

    @staticmethod
    async def handle_load_success(work_id: int) -> None:
        """robot-events의 success_load1(베드 집기 성공) 수신 처리 (PRD 5장): board_stock을
        RESERVED→EMPTY로, 주문을 DISPATCHING→LOADING으로 바꾼다. 알 수 없는 work_id이거나
        이미 처리된 경우(중복 수신)는 조용히 무시한다.

        이 물리적 사실(베드를 집었다는 것)은 뒤이은 프린터 배정 성패와 무관하게 먼저
        커밋한다 — 그래야 배치 명령 전송이 실패해도 board_stock이 틀린 상태(RESERVED)로
        되돌아가지 않는다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.DISPATCHING:
                await session.rollback()
                return

            task = await RobotTaskRepository.get_active_load_for_order_locked(session, work_id)
            if task is None or task.start_pos_id is None:
                await session.rollback()
                return

            now = datetime.utcnow()
            board = await BoardStockRepository.get_locked(session, task.start_pos_id)
            if board is not None and board.status == BoardStockStatus.RESERVED:
                board.status = BoardStockStatus.EMPTY
                board.updated_at = now

            order.status = OrderStatus.LOADING
            order.updated_at = now
            task.status = TaskStatus.RUNNING
            task.started_at = task.started_at or now
            await session.flush()

            await broadcast_to_web(
                session, "order.updated", OrderOut.model_validate(order).model_dump(mode="json")
            )
            await broadcast_to_web(
                session, "board_stock.updated", await WorkRequestService._board_stock_snapshot(session)
            )
            await session.commit()

        await WorkRequestService._dispatch_place_command(work_id)

    @staticmethod
    async def _dispatch_place_command(work_id: int) -> None:
        """success_load1 이후, 비어있는 프린터를 찾아 예약하고 배치 명령(sd_pos_id)을
        robot-commands에 보낸다. 빈 프린터가 없거나 전송에 실패하면 프린터는 배정하지
        않은 채로 로그만 남긴다 — 프린터가 빌 때 자동으로 재시도하는 로직은 아직 없다
        (후속 보강 필요)."""
        async with AsyncSessionLocal() as session:
            printer = await PrinterRepository.first_empty_locked(session)
            if printer is None:
                await session.rollback()
                logger.warning(
                    "success_load1 처리했지만 빈 프린터가 없어 배치 명령을 보내지 못함 (work_id=%s)", work_id
                )
                return

            now = datetime.utcnow()
            printer.status = PrinterStatus.RESERVED
            printer.current_order_id = work_id
            printer.updated_at = now

            order = await OrderRepository.get_locked(session, work_id)
            task = await RobotTaskRepository.get_active_load_for_order_locked(session, work_id)
            if order is not None:
                order.printer_slot = printer.slot
                order.updated_at = now
            if task is not None:
                task.printer_slot = printer.slot
                task.sd_pos_id = printer.slot
            await session.flush()

            produced = await SqsProducerService.produce_place_command(work_id=work_id, sd_pos_id=printer.slot)
            if not produced:
                await session.rollback()
                logger.error(
                    "robot-commands 배치 명령 전송 실패 (work_id=%s, sd_pos_id=%s)", work_id, printer.slot
                )
                return

            if order is not None:
                await broadcast_to_web(
                    session, "order.updated", OrderOut.model_validate(order).model_dump(mode="json")
                )
            await broadcast_to_web(
                session, "printer.updated", PrinterOut.model_validate(printer).model_dump(mode="json")
            )
            await session.commit()

    @staticmethod
    async def handle_load_pick_failed(work_id: int) -> None:
        """robot-events의 베드 집기 실패 이벤트(예: {"work_id":1,"type":"fail_load1",
        "stage":"load1"}) 수신 처리. 로봇이 베드를 집지 못했을 뿐 board_stock/주문
        상태는 그대로 둔다(여전히 RESERVED/DISPATCHING) — 사람이 적재대를 바로잡고
        나면 같은 슬롯으로 재시도하면 되기 때문이다. 웹에 알럿만 띄운다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.DISPATCHING:
                await session.rollback()
                return

            await broadcast_to_web(
                session,
                "alert.load_pick_failed",
                {"work_id": work_id, "reason": AlertReason.LOAD_PICK_FAILED.value},
            )
            await session.commit()

    @staticmethod
    async def retry_load(work_id: int) -> None:
        """베드 집기 실패(fail_load1) 알럿에서 사람이 적재대를 확인하고 "확인"을 누르면,
        그때 디스패치됐던 것과 같은 start_pos_id로 LOAD(집기) 명령을 SQS에 다시 보낸다.
        이 시점엔 아직 집기 전이라 프린터(sd_pos_id)는 관여하지 않는다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.DISPATCHING:
                await session.rollback()
                raise LoadRetryNotFoundError(work_id)

            task = await RobotTaskRepository.get_active_load_for_order_locked(session, work_id)
            if task is None or task.start_pos_id is None:
                await session.rollback()
                raise LoadRetryNotFoundError(work_id)

            start_pos_id = task.start_pos_id
            await session.rollback()

        produced = await SqsProducerService.produce_load_command(work_id=work_id, start_pos_id=start_pos_id)
        if not produced:
            raise SqsProduceError(work_id)

    @staticmethod
    async def _insert_order(
        session: AsyncSession, shape: Shape | None, customer_name: str | None
    ) -> Order:
        chosen_shape = shape or random.choice(_SHAPE_CHOICES)
        now = datetime.utcnow()
        name = customer_name or f"손님-{random.randint(0, 9999):04d}"
        user = await UserRepository.add(session, name=name, created_at=now)

        order = Order(
            user_id=user.id,
            shape=chosen_shape,
            print_duration_sec=SHAPE_PRINT_DURATION_SEC[chosen_shape],
            status=OrderStatus.WAITING,
            source=OrderSource.MANUAL,
            created_at=now,
            updated_at=now,
        )
        OrderRepository.add(session, order)
        await session.flush()
        await broadcast_to_web(session, "order.created", OrderOut.model_validate(order).model_dump(mode="json"))
        await session.commit()
        return order

    @staticmethod
    async def _board_stock_snapshot(session: AsyncSession) -> dict:
        rows = await BoardStockRepository.list_all(session)
        return {"slots": [{"slot": r.slot, "status": r.status.value} for r in rows]}
