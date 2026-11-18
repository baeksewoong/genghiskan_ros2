"""작업요청(SQS 디스패치) 처리 — 주문이 만들어지는 유일한 경로다
(PRD: assets/docs/prd-work-request-sqs.md). 요청 하나를 받을 때마다 그 자리에서
즉시 베드를 확인해 판정한다.

LOAD는 두 단계다: dispatch 시점엔 베드(start_pos_id)만 확인해서 집기 명령을 보내고,
프린터는 아직 고르지 않는다. 로봇이 베드 집기에 성공(success_load1)했다고 보고하면
그때 비어있는 프린터를 찾아 배치 명령(sd_pos_id)을 보낸다 — dispatch와 배치 사이에
프린터 가용성이 바뀔 수 있어서, 더 정확한 시점에 고르기 위함."""

import logging
import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.events import broadcast_to_web
from app.enums import AlertReason, OrderStatus, PrinterStatus, Shape
from app.models import Order, RobotTask
from app.repositories.board_stock_repository import BoardStockRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.printer_repository import PrinterRepository
from app.repositories.receive_pos_repository import ReceivePosRepository
from app.repositories.robot_task_repository import RobotTaskRepository
from app.repositories.user_repository import UserRepository
from app.services.order_presenter import build_order_out
from app.services.printer_presenter import build_printer_out
from app.services.sqs_producer_service import SqsProducerService
from app.services.teaching_pendant_service import TeachingPendantService

logger = logging.getLogger(__name__)

_SHAPE_CHOICES = list(Shape)


class BoardEmptyError(Exception):
    """적재대에 베드가 비어있어 작업요청을 디스패치할 수 없을 때. 주문 행 자체는
    이미 WAITING으로 저장돼 있다 (PRD 3장 2단계)."""

    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"board empty for order {order_id}")


class UnloadRetryNotFoundError(Exception):
    """완성품 집기 실패(fail_unload1) 알럿에서 "확인"을 눌렀는데, 재시도할 주문
    (PRINT_DONE)을 찾을 수 없을 때."""

    def __init__(self, work_id: int):
        self.work_id = work_id
        super().__init__(f"no unload1 to retry for work {work_id}")


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

        # 티칭 팬던트(실물 로봇 조그) 세션이 활성 중이면 로봇이 조그/그리퍼 명령
        # 전용이어야 하므로 LOAD를 보내지 않는다 (PRD: prd-teaching-pendant.md 3장 B).
        # 베드가 없을 때(BoardEmptyError)와 달리 이건 에러가 아니다 — 주문은 그대로
        # WAITING으로 남기고 201(대기 등록) 응답을 돌려준다. 조그 세션 체크를 베드
        # 확인보다 먼저 두어, 세션 중에는 베드 예약조차 건드리지 않는다.
        if TeachingPendantService.is_session_active():
            logger.info(
                "조그 세션이 활성 중이라 작업요청 LOAD를 보류합니다 (order_id=%s, WAITING 유지)", order.id
            )
            return order

        async with AsyncSessionLocal() as session2:
            board = await BoardStockRepository.top_occupied_locked(session2)
            if board is None:
                await broadcast_to_web(
                    session2, "alert.refill_required", {"reason": AlertReason.BOARD_STOCK_EMPTY.value}
                )
                await session2.commit()
                raise BoardEmptyError(order.id)

            now = datetime.utcnow()
            board.reserve(now)

            task = RobotTask.dispatch_load_request(order_id=order.id, start_pos_id=board.slot, now=now)
            RobotTaskRepository.add(session2, task)

            order_db = await OrderRepository.get_locked(session2, order.id)
            order_db.mark_dispatching(now)
            await session2.flush()

            # TODO: 실제 적재대 슬롯(board.slot)이 아니라 3으로 하드코딩해 발행 중 — 테스트용 임시 조치.
            produced = await SqsProducerService.produce_load_command(work_id=order.id, start_pos_id=3)
            if not produced:
                await session2.rollback()
                raise SqsProduceError(order.id)

            await broadcast_to_web(
                session2, "order.updated", (await build_order_out(session2, order_db)).model_dump(mode="json")
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
            if board is not None:
                board.release(now)

            order.mark_loading(now)
            task.mark_running(now)
            await session.flush()

            await broadcast_to_web(
                session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
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
            printer.reserve(work_id, now)

            order = await OrderRepository.get_locked(session, work_id)
            task = await RobotTaskRepository.get_active_load_for_order_locked(session, work_id)
            if order is not None:
                order.assign_printer(printer.slot, now)
            if task is not None:
                task.assign_printer(printer.slot)
            await session.flush()

            # TODO: 실제 프린터 슬롯(printer.slot)이 아니라 3으로 하드코딩해 발행 중 — 테스트용 임시 조치.
            produced = await SqsProducerService.produce_place_command(work_id=work_id, sd_pos_id=3)
            if not produced:
                await session.rollback()
                logger.error(
                    "robot-commands 배치 명령 전송 실패 (work_id=%s, sd_pos_id=%s)", work_id, printer.slot
                )
                return

            if order is not None:
                await broadcast_to_web(
                    session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
                )
            await broadcast_to_web(
                session, "printer.updated", (await build_printer_out(session, printer)).model_dump(mode="json")
            )
            await session.commit()

    @staticmethod
    async def handle_place_success(work_id: int) -> None:
        """robot-events의 success_load2(프린터 배치 성공) 수신 처리: 주문을
        LOADING→PRINTING으로, 배정된 프린터를 RESERVED→PRINTING(타이머 시작)으로,
        LOAD 작업을 RUNNING→SUCCEEDED로 바꾼다. 그 뒤로는 기존 TimerService의
        출력 타이머 스윕이 처리한다. 알 수 없는
        work_id이거나 이미 처리된 경우(중복 수신)는 조용히 무시한다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.LOADING:
                await session.rollback()
                return

            task = await RobotTaskRepository.get_active_load_for_order_locked(session, work_id)
            if task is None or task.printer_slot is None:
                await session.rollback()
                return

            printer = await PrinterRepository.get_locked(session, task.printer_slot)
            if printer is None or printer.status != PrinterStatus.RESERVED:
                await session.rollback()
                return

            now = datetime.utcnow()
            task.mark_succeeded(now)
            order.mark_printing(now)
            printer.start_printing(now, now + timedelta(seconds=order.print_duration_sec))
            await session.flush()

            await broadcast_to_web(
                session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
            )
            await broadcast_to_web(
                session, "printer.updated", (await build_printer_out(session, printer)).model_dump(mode="json")
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
    async def handle_unload1_success(work_id: int) -> bool:
        """robot-events의 success_unload1(프린터에서 완성품 꺼내기 성공) 수신 처리.

        1) 물리적 사실을 먼저 커밋한다: 주문 PRINT_DONE→UNLOADING, 프린터 DONE→EMPTY.
           뒤이은 unload2 전송 성패와 무관하게 프린터는 이미 비었기 때문이다.
        2) 비어있는 수령대(1번 우선, 1번이 차 있으면 2번)를 골라 unload2를 보낸다.
           둘 다 차 있으면 웹에 알럿을 띄우고 대기한다 — 사람이 "수령하기"로 자리를
           비우면 dispatch_pending_unload2가 자동으로 이어서 보낸다.

        PRINT_DONE 주문이 아니면(알 수 없는 work_id, 중복 수신 등) 조용히 무시한다.
        반환값: unload2 발행 성공 여부."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.PRINT_DONE:
                await session.rollback()
                logger.warning("success_unload1 무시: PRINT_DONE 주문이 아님 (work_id=%s)", work_id)
                return False

            now = datetime.utcnow()
            order.mark_unloading(now)
            printer = (
                await PrinterRepository.get_locked(session, order.printer_slot)
                if order.printer_slot is not None
                else None
            )
            if printer is not None and printer.current_order_id == order.id and printer.status == PrinterStatus.DONE:
                printer.release_after_unload(now)
            else:
                printer = None
            await session.flush()

            await broadcast_to_web(
                session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
            )
            if printer is not None:
                await broadcast_to_web(
                    session, "printer.updated", (await build_printer_out(session, printer)).model_dump(mode="json")
                )
            await session.commit()

        return await WorkRequestService._dispatch_unload2(work_id, alert_if_full=True)

    @staticmethod
    async def dispatch_pending_unload2() -> bool:
        """수령대 자리가 났을 때(“수령하기” 직후) 호출한다. 수령대가 가득 차서 대기 중인
        주문(UNLOADING, receive_pos_id 없음)이 있으면 가장 오래 기다린 것부터 unload2를
        보낸다. 대기 주문이 없으면 아무것도 하지 않는다. 반환값: 발행 여부."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.oldest_waiting_receive_pos_locked(session)
            work_id = order.id if order is not None else None
            await session.rollback()
        if work_id is None:
            return False
        return await WorkRequestService._dispatch_unload2(work_id, alert_if_full=False)

    @staticmethod
    async def _dispatch_unload2(work_id: int, *, alert_if_full: bool) -> bool:
        """UNLOADING이면서 수령대 미배정인 주문에 빈 수령대를 배정하고 unload2를 보낸다.
        수령대가 가득 차면 (alert_if_full일 때) 알럿을 띄우고 대기 상태로 둔다.
        전송에 실패하면 배정을 롤백한다 — 대기 상태로 남아 다음 "수령하기" 때 재시도된다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.UNLOADING or order.receive_pos_id is not None:
                await session.rollback()
                return False

            receive_pos = await ReceivePosRepository.first_empty_locked(session)
            if receive_pos is None:
                logger.warning("수령대가 모두 차 있어 unload2 대기 (work_id=%s)", work_id)
                if alert_if_full:
                    await broadcast_to_web(
                        session,
                        "alert.receive_pos_full",
                        {"work_id": work_id, "reason": AlertReason.RECEIVE_POS_FULL.value},
                    )
                    await session.commit()
                else:
                    await session.rollback()
                return False

            receive_pos_id = receive_pos.pos_id
            now = datetime.utcnow()
            receive_pos.reserve(work_id, now)
            order.assign_receive_pos(receive_pos_id, now)
            await session.flush()

            produced = await SqsProducerService.produce_unload2_command(
                work_id=work_id, receive_pos_id=receive_pos_id
            )
            if not produced:
                await session.rollback()
                logger.error(
                    "robot-commands unload2 명령 전송 실패 (work_id=%s, receive_pos_id=%s)", work_id, receive_pos_id
                )
                return False

            await broadcast_to_web(
                session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
            )
            await broadcast_to_web(
                session, "receive_pos.updated", await WorkRequestService._receive_pos_snapshot(session)
            )
            # 수령대 가득 참 알럿이 떠 있었다면 닫는다 (해당 work_id에 한해 프론트가 처리).
            await broadcast_to_web(session, "alert.receive_pos_full_cleared", {"work_id": work_id})
            await session.commit()
            return True

    @staticmethod
    async def handle_unload2_success(work_id: int) -> None:
        """robot-events의 success_unload2(수령대에 완성품 내려놓기 성공) 수신 처리:
        주문을 UNLOADING→READY_FOR_PICKUP으로, 수령대(receive_pos)를 RESERVED→OCCUPIED로
        바꾼다. 수령대는 "수령하기"(PICKED_UP)를 누를 때까지 점유 상태로 남는다. 알 수 없는
        work_id이거나 이미 처리된 경우(중복 수신)는 조용히 무시한다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.UNLOADING or order.receive_pos_id is None:
                await session.rollback()
                return

            now = datetime.utcnow()
            order.mark_ready_for_pickup(now)
            receive_pos = await ReceivePosRepository.get_by_order_locked(session, work_id)
            if receive_pos is not None:
                receive_pos.occupy(now)
            await session.flush()
            await broadcast_to_web(
                session, "order.updated", (await build_order_out(session, order)).model_dump(mode="json")
            )
            await broadcast_to_web(
                session, "receive_pos.updated", await WorkRequestService._receive_pos_snapshot(session)
            )
            await session.commit()

    @staticmethod
    async def handle_unload1_failed(work_id: int) -> None:
        """robot-events의 fail_unload1(프린터에서 완성품 집기 실패) 수신 처리. 상태는
        바꾸지 않고 웹에 "작업대에 베드를 확인하세요!" 알럿만 띄운다."""
        async with AsyncSessionLocal() as session:
            await broadcast_to_web(
                session,
                "alert.unload_pick_failed",
                {"work_id": work_id, "reason": AlertReason.UNLOAD_PICK_FAILED.value},
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

            await session.rollback()

        # TODO: 실제 start_pos_id가 아니라 3으로 하드코딩해 발행 중 — 테스트용 임시 조치.
        produced = await SqsProducerService.produce_load_command(
            work_id=work_id, start_pos_id=3, retry_token=uuid.uuid4().hex[:12]
        )
        if not produced:
            raise SqsProduceError(work_id)

    @staticmethod
    async def retry_unload1(work_id: int) -> None:
        """완성품 집기 실패(fail_unload1) 알럿에서 사람이 작업대의 베드를 확인하고
        "확인"을 누르면, 같은 work_id로 unload1 명령을 다시 보낸다. fail_unload1은
        상태를 바꾸지 않으므로 주문은 여전히 PRINT_DONE이어야 한다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get(session, work_id)
            if order is None or order.status != OrderStatus.PRINT_DONE:
                raise UnloadRetryNotFoundError(work_id)

        # TODO: 실제 프린터 슬롯이 아니라 3으로 하드코딩해 발행 중 — TimerService의 첫 unload1과 동일한 임시 조치.
        produced = await SqsProducerService.produce_unload_command(
            work_id=work_id, sd_pos_id=3, retry_token=uuid.uuid4().hex[:12]
        )
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

        order = Order.create_new(user_id=user.id, shape=chosen_shape, now=now)
        OrderRepository.add(session, order)
        await session.flush()
        await broadcast_to_web(session, "order.created", (await build_order_out(session, order)).model_dump(mode="json"))
        await session.commit()
        return order

    @staticmethod
    async def _board_stock_snapshot(session: AsyncSession) -> dict:
        rows = await BoardStockRepository.list_all(session)
        return {"slots": [{"slot": r.slot, "status": r.status.value} for r in rows]}

    @staticmethod
    async def _receive_pos_snapshot(session: AsyncSession) -> dict:
        rows = await ReceivePosRepository.list_all(session)
        return {
            "positions": [
                {"pos_id": r.pos_id, "status": r.status.value, "current_order_id": r.current_order_id}
                for r in rows
            ]
        }
