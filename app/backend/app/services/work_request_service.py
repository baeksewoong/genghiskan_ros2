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
from app.core.runtime import runtime
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
    """적재대에 베드가 하나도 없어 작업요청 자체를 접수하지 않을 때. 주문 행은
    아직 만들어지지 않는다 — 사람이 적재대를 채우고 "채우기 완료"를 누른 뒤
    다시 요청해야 한다."""


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


class PlaceConfirmNotFoundError(Exception):
    """프린터 배치 실패(fail_load2) 알럿에서 "네"를 눌렀는데, 확인할 LOADING 주문을
    찾을 수 없을 때(알 수 없는 work_id, 이미 다른 상태로 진행됨 등)."""

    def __init__(self, work_id: int):
        self.work_id = work_id
        super().__init__(f"no LOADING order to confirm place for work_id {work_id}")


class WorkRequestService:
    @staticmethod
    async def create(
        session: AsyncSession,
        shape: Shape | None,
        customer_name: str | None = None,
    ) -> Order:
        # 티칭 팬던트(실물 로봇 조그) 세션이 활성 중이면 로봇이 조그/그리퍼 명령
        # 전용이어야 하므로 LOAD를 보내지 않는다 (PRD: prd-teaching-pendant.md 3장 B).
        # 베드가 없을 때(BoardEmptyError)와 달리 이건 에러가 아니다 — 주문은 WAITING으로
        # 등록하고 201(대기 등록) 응답을 돌려준다. 조그 세션 체크를 베드 확인보다 먼저
        # 두어, 세션 중에는 베드 예약조차 건드리지 않는다.
        if TeachingPendantService.is_session_active():
            order = await WorkRequestService._insert_order(session, shape, customer_name)
            logger.info(
                "조그 세션이 활성 중이라 작업요청 LOAD를 보류합니다 (order_id=%s, WAITING 유지)", order.id
            )
            return order

        # 적재대에 베드가 하나도 없으면 주문 자체를 만들지 않는다 — 로봇 바쁨/프린터
        # 가득 참과 달리, 이건 사람이 적재대를 채우고 "채우기 완료"를 눌러야 풀리는
        # 상황이라 자동 재시도 대기열에 넣어두는 의미가 없다.
        await WorkRequestService._ensure_board_available()

        order = await WorkRequestService._insert_order(session, shape, customer_name)
        dispatched = await WorkRequestService._try_dispatch_load1(order.id)
        return dispatched if dispatched is not None else order

    @staticmethod
    async def _ensure_board_available() -> None:
        """적재대에 베드가 하나도 없으면 BoardEmptyError를 던진다 — 호출 시점에
        아직 주문을 만들지 않았으므로 DB에 아무것도 남기지 않는다. "채우기 완료"
        전까지는 같은 요청을 다시 보내도 매번 이 단계에서 걸린다."""
        async with AsyncSessionLocal() as session:
            board = await BoardStockRepository.top_occupied_locked(session)
            if board is None:
                await broadcast_to_web(
                    session, "alert.refill_required", {"reason": AlertReason.BOARD_STOCK_EMPTY.value}
                )
                await session.commit()
                raise BoardEmptyError()
            await session.rollback()

    @staticmethod
    async def _try_dispatch_load1(order_id: int) -> Order | None:
        """WAITING 주문의 load1(베드 집기)을 디스패치한다. LOAD1~LOAD2,
        UNLOAD1~UNLOAD2는 각각 한 세트로 묶여야 해서 로봇이 이미 다른 작업
        중이면 끼어들면 안 된다 — get_active_real_robot_task_locked로 확인해,
        로봇이 바쁘면 아무것도 하지 않고 None을 반환해 WAITING으로 둔다(로봇이
        비면 dispatch_pending_robot_work가 이어서 재시도한다). 베드가 없으면
        BoardEmptyError, SQS 발행 실패면 SqsProduceError를 그대로 던진다.

        디스패치 순서 보장: WAITING 중 이 주문보다 먼저 들어온 게 있으면(예: 로봇이
        바빠서, 혹은 베드가 없어서 먼저 밀려 있던 주문) 이 주문을 새치기해서
        디스패치하지 않는다 — 가장 오래 기다린 주문부터 처리되도록 None을 반환해
        그대로 WAITING으로 둔다(dispatch_pending_robot_work가 순서대로 이어서 처리한다).

        빈 프린터 선점: 빈 프린터가 하나도 없으면 load1도 보내지 않는다. 로봇이
        베드를 집고 나서(success_load1) 놓을 프린터가 없으면 로봇이 베드를 든 채로
        멈춰버리고, 로봇이 하나뿐이라 그 사이엔 unload조차 못 보내 영구적으로
        멈추는 상태(dead-lock)가 되기 때문이다. 프린터가 비는 즉시(success_unload2
        등) dispatch_pending_robot_work가 재시도한다."""
        async with AsyncSessionLocal() as session2:
            busy = await RobotTaskRepository.get_active_real_robot_task_locked(session2)
            if busy is not None:
                await session2.rollback()
                logger.info(
                    "로봇이 다른 작업(LOAD/UNLOAD) 중이라 load1 디스패치를 보류합니다 (order_id=%s)",
                    order_id,
                )
                return None

            waiting_orders = await OrderRepository.get_waiting(session2)
            if waiting_orders and waiting_orders[0].id != order_id:
                oldest_waiting_id = waiting_orders[0].id
                await session2.rollback()
                logger.info(
                    "더 오래 기다린 작업요청(order_id=%s)이 있어 load1 디스패치를 보류합니다 (order_id=%s)",
                    oldest_waiting_id,
                    order_id,
                )
                return None

            if await PrinterRepository.first_empty_locked(session2) is None:
                await session2.rollback()
                logger.info(
                    "빈 프린터가 없어 load1 디스패치를 보류합니다 (order_id=%s)", order_id
                )
                return None

            board = await BoardStockRepository.top_occupied_locked(session2)
            if board is None:
                await broadcast_to_web(
                    session2, "alert.refill_required", {"reason": AlertReason.BOARD_STOCK_EMPTY.value}
                )
                await session2.commit()
                raise BoardEmptyError()

            now = datetime.utcnow()
            board.reserve(now)

            task = RobotTask.dispatch_load_request(order_id=order_id, start_pos_id=board.slot, now=now)
            RobotTaskRepository.add(session2, task)

            order_db = await OrderRepository.get_locked(session2, order_id)
            order_db.mark_dispatching(now)
            await session2.flush()

            produced = await SqsProducerService.produce_load_command(work_id=order_id, start_pos_id=board.slot)
            if not produced:
                await session2.rollback()
                raise SqsProduceError(order_id)

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

            task = await RobotTaskRepository.get_active_task_for_order_locked(session, work_id)
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
            task = await RobotTaskRepository.get_active_task_for_order_locked(session, work_id)
            if order is not None:
                order.assign_printer(printer.slot, now)
            if task is not None:
                task.assign_printer(printer.slot)
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

            task = await RobotTaskRepository.get_active_task_for_order_locked(session, work_id)
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

        # load1~load2 한 세트가 끝나 로봇이 비었다 — 밀려 있던 unload1/load1을 이어서 시도한다.
        await WorkRequestService.dispatch_pending_robot_work()

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
    async def handle_place_failed(work_id: int) -> None:
        """robot-events의 프린터 배치 실패 이벤트(예: {"work_id":1,"type":"fail_load2"})
        수신 처리. 로봇/주문 상태는 그대로 둔다(여전히 LOADING) — 사람이 작업대를
        눈으로 확인해 "네"(confirm_place)/"아니오"(관리자 문의)로 처리하게 웹에
        알럿만 띄운다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get_locked(session, work_id)
            if order is None or order.status != OrderStatus.LOADING:
                await session.rollback()
                return

            await broadcast_to_web(
                session,
                "alert.place_failed",
                {"work_id": work_id, "reason": AlertReason.PLACE_FAILED.value},
            )
            await session.commit()

    @staticmethod
    async def confirm_place(work_id: int) -> None:
        """프린터 배치 실패(fail_load2) 알럿에서 사람이 작업대를 눈으로 확인하고
        "네"를 누르면, 로봇이 보낸 것처럼 success_load2를 robot-events에 대신
        주입한다. 기존 success_load2 처리 경로(handle_place_success)를 그대로
        타므로 여기서는 상태를 직접 바꾸지 않는다."""
        async with AsyncSessionLocal() as session:
            order = await OrderRepository.get(session, work_id)
            if order is None or order.status != OrderStatus.LOADING:
                raise PlaceConfirmNotFoundError(work_id)

        produced = await SqsProducerService.produce_manual_robot_event(
            {"type": "success_load2", "work_id": work_id}, log_extra={"work_id": work_id}
        )
        if not produced:
            raise SqsProduceError(work_id)

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

            task = await RobotTaskRepository.get_active_task_for_order_locked(session, work_id)
            if task is not None:
                task.mark_running(now)

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
                # work_id당 한 번만 알린다 — 사람이 "확인"으로 닫은 뒤에도 조건이
                # 여전하면(특히 타이머 스윕 재시도 때) 모달이 다시 뜨지 않게 한다.
                if alert_if_full and work_id not in runtime.receive_pos_full_alerted_work_ids:
                    runtime.receive_pos_full_alerted_work_ids.add(work_id)
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
            runtime.receive_pos_full_alerted_work_ids.discard(work_id)
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

            task = await RobotTaskRepository.get_active_task_for_order_locked(session, work_id)
            if task is not None:
                task.mark_succeeded(now)

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

        # unload1~unload2 한 세트가 끝나 로봇이 비었다 — 밀려 있던 unload1/load1을 이어서 시도한다.
        await WorkRequestService.dispatch_pending_robot_work()

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

            task = await RobotTaskRepository.get_active_task_for_order_locked(session, work_id)
            if task is None or task.start_pos_id is None:
                await session.rollback()
                raise LoadRetryNotFoundError(work_id)

            start_pos_id = task.start_pos_id
            await session.rollback()

        produced = await SqsProducerService.produce_load_command(
            work_id=work_id, start_pos_id=start_pos_id, retry_token=uuid.uuid4().hex[:12]
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
            if order is None or order.status != OrderStatus.PRINT_DONE or order.printer_slot is None:
                raise UnloadRetryNotFoundError(work_id)
            printer_slot = order.printer_slot

        produced = await SqsProducerService.produce_unload_command(
            work_id=work_id, sd_pos_id=printer_slot, retry_token=uuid.uuid4().hex[:12]
        )
        if not produced:
            raise SqsProduceError(work_id)

    @staticmethod
    async def _try_dispatch_unload1(order_id: int) -> bool:
        """출력이 끝난(PRINT_DONE) 주문의 unload1(완성품 꺼내기)을 디스패치한다.
        _try_dispatch_load1과 같은 이유로 로봇이 이미 다른 작업 중이면 디스패치하지
        않는다 — 그 경우 이 주문은 robot_task가 없는 PRINT_DONE으로 남아
        dispatch_pending_robot_work가 로봇이 빌 때 다시 찾아 재시도한다.

        수령대 선점: 수령대(1, 2)가 모두 차 있으면 unload1조차 보내지 않는다 —
        로봇이 완성품을 집고 나면 내려놓을 곳이 없어 든 채로 멈춰버리고, 로봇이
        하나뿐이라 그 사이엔 load1도 못 보내 사실상 멈추는 상태가 되기 때문이다
        (_try_dispatch_load1의 빈 프린터 선점과 같은 이유). 이 경우 웹에 알럿만
        띄우고 이 주문은 그대로 robot_task 없는 PRINT_DONE으로 남아, 수령대 자리가
        나면("수령하기") dispatch_pending_robot_work가 다시 찾아 재시도한다."""
        async with AsyncSessionLocal() as session:
            busy = await RobotTaskRepository.get_active_real_robot_task_locked(session)
            if busy is not None:
                await session.rollback()
                return False

            order = await OrderRepository.get_locked(session, order_id)
            if order is None or order.status != OrderStatus.PRINT_DONE or order.printer_slot is None:
                await session.rollback()
                return False

            if await ReceivePosRepository.first_empty_locked(session) is None:
                logger.info(
                    "수령대가 모두 차 있어 unload1 디스패치를 보류합니다 (work_id=%s)", order_id
                )
                # work_id당 한 번만 알린다 — 이 함수는 타이머 스윕(0.5초 간격)마다도
                # 호출되므로, 가드가 없으면 조건이 풀리기 전까지 매 틱 다시 알려
                # 사람이 "확인"으로 닫아도 모달이 거의 바로 다시 뜬다.
                if order_id not in runtime.receive_pos_full_alerted_work_ids:
                    runtime.receive_pos_full_alerted_work_ids.add(order_id)
                    await broadcast_to_web(
                        session,
                        "alert.receive_pos_full",
                        {"work_id": order_id, "reason": AlertReason.RECEIVE_POS_FULL.value},
                    )
                    await session.commit()
                else:
                    await session.rollback()
                return False

            now = datetime.utcnow()
            task = RobotTask.dispatch_unload_request(order_id=order_id, printer_slot=order.printer_slot, now=now)
            RobotTaskRepository.add(session, task)
            await session.flush()

            produced = await SqsProducerService.produce_unload_command(
                work_id=order_id, sd_pos_id=order.printer_slot
            )
            if not produced:
                await session.rollback()
                logger.error("robot-commands unload1 명령 전송 실패 (work_id=%s)", order_id)
                return False

            # 이전에 수령대 가득 참으로 보류됐었다면(해당 work_id에 한해) 알럿을 내린다.
            runtime.receive_pos_full_alerted_work_ids.discard(order_id)
            await broadcast_to_web(session, "alert.receive_pos_full_cleared", {"work_id": order_id})
            await session.commit()
            return True

    @staticmethod
    async def dispatch_pending_robot_work() -> None:
        """로봇이 방금 자유로워졌을 때(success_load2/success_unload2 직후)나 타이머
        스윕 뒤에 호출한다. LOAD1~LOAD2, UNLOAD1~UNLOAD2는 각각 한 세트로 묶여야
        하므로, 로봇이 이미 다른 작업 중이면 아무것도 하지 않는다. 비어있으면 밀린
        unload1(출력은 끝났지만 아직 못 꺼낸 주문)을 먼저 처리하고, 없으면 대기
        중인(WAITING) 주문의 load1을 가장 오래된 것부터 디스패치한다 — 프린터를
        먼저 비우는 쪽이 전체 처리량에 유리해서 unload를 우선한다."""
        async with AsyncSessionLocal() as session:
            busy = await RobotTaskRepository.get_active_real_robot_task_locked(session)
            if busy is not None:
                await session.rollback()
                return

            pending_unload = await OrderRepository.oldest_print_done_without_active_task(session)
            pending_unload_id = pending_unload.id if pending_unload is not None else None

            waiting_order_id = None
            if pending_unload_id is None and not TeachingPendantService.is_session_active():
                waiting_orders = await OrderRepository.get_waiting(session)
                waiting_order_id = waiting_orders[0].id if waiting_orders else None

            await session.rollback()

        try:
            if pending_unload_id is not None:
                await WorkRequestService._try_dispatch_unload1(pending_unload_id)
            elif waiting_order_id is not None:
                await WorkRequestService._try_dispatch_load1(waiting_order_id)
        except (BoardEmptyError, SqsProduceError):
            logger.exception("dispatch_pending_robot_work 디스패치 실패")

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
