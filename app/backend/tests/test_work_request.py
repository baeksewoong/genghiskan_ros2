from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.enums import BoardStockStatus, OrderStatus, PrinterStatus, ReceivePosStatus, TaskStatus
from app.models import BoardStock, Order, Printer, ReceivePos, RobotTask
from app.repositories.board_stock_repository import BoardStockRepository
from app.services.board_stock_service import BoardStockService
from app.services.sqs_producer_service import SqsProducerService
from app.services.order_service import OrderService
from app.services.work_request_service import (
    BoardEmptyError,
    SqsProduceError,
    UnloadRetryNotFoundError,
    WorkRequestService,
)

pytestmark = pytest.mark.asyncio


async def _occupy(slot: int) -> None:
    async with AsyncSessionLocal() as session:
        board = await session.get(BoardStock, slot)
        board.status = BoardStockStatus.OCCUPIED
        board.updated_at = datetime.utcnow()
        await session.commit()


async def _fill_all_printers() -> None:
    async with AsyncSessionLocal() as session:
        for slot in (1, 2, 3):
            printer = await session.get(Printer, slot)
            printer.status = PrinterStatus.PRINTING
            printer.updated_at = datetime.utcnow()
        await session.commit()


async def test_board_empty_rejects_without_creating_order():
    """베드가 없으면 작업요청 자체를 접수하지 않는다 — 주문도, robot_tasks도
    생성되지 않는다."""
    async with AsyncSessionLocal() as session:
        with pytest.raises(BoardEmptyError):
            await WorkRequestService.create(session, shape=None)

    async with AsyncSessionLocal() as session:
        orders = (await session.execute(select(Order))).scalars().all()
        assert orders == []

        tasks = (await session.execute(select(RobotTask))).scalars().all()
        assert tasks == []


async def test_board_empty_requests_never_dispatch_until_refill(monkeypatch):
    """베드가 없는 동안 들어온 요청은 전부 거부되고 아무것도 남기지 않는다 —
    "채우기 완료"를 눌러야 그 다음 요청부터 정상 접수·디스패치된다."""
    sent: list[dict] = []

    async def _fake_produce_load(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce_load)

    async with AsyncSessionLocal() as session:
        with pytest.raises(BoardEmptyError):
            await WorkRequestService.create(session, shape=None)
    async with AsyncSessionLocal() as session:
        with pytest.raises(BoardEmptyError):
            await WorkRequestService.create(session, shape=None)

    assert sent == []  # 로봇에는 아무것도 나가지 않았다
    async with AsyncSessionLocal() as session:
        assert (await session.execute(select(Order))).scalars().all() == []

    async with AsyncSessionLocal() as session:
        await BoardStockService.refill_complete(session)

    # 채우기 완료 이후의 요청은 평소처럼 즉시 디스패치된다.
    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)
    assert order.status == OrderStatus.DISPATCHING
    assert sent == [{"work_id": order.id, "start_pos_id": 3}]


async def test_dispatch_blocked_when_no_empty_printer_to_avoid_deadlock(monkeypatch):
    """프린터가 전부 차 있으면 load1 자체를 보내지 않는다 — 로봇이 베드를 집고도
    놓을 곳이 없어 들고 멈춰버리면, 로봇이 하나뿐이라 그 사이엔 unload조차 보낼 수
    없어 영구적으로 멈추기 때문이다. 프린터가 비면 밀린 load1이 자동으로 이어진다."""
    await _occupy(2)
    await _fill_all_printers()
    sent: list[dict] = []

    async def _fake_produce_load(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce_load)

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)
        assert order.status == OrderStatus.WAITING

    assert sent == []

    async with AsyncSessionLocal() as session:
        board = await session.get(BoardStock, 2)
        assert board.status == BoardStockStatus.OCCUPIED  # 예약되지 않음

        tasks = (await session.execute(select(RobotTask))).scalars().all()
        assert tasks == []

    async with AsyncSessionLocal() as session:
        printer = await session.get(Printer, 1)
        printer.status = PrinterStatus.EMPTY
        printer.current_order_id = None
        await session.commit()

    await WorkRequestService.dispatch_pending_robot_work()

    assert sent == [{"work_id": order.id, "start_pos_id": 2}]
    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order.id)
        assert refreshed.status == OrderStatus.DISPATCHING


async def test_successful_dispatch_reserves_board_only(monkeypatch):
    await _occupy(2)
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(True))

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)
        assert order.status == OrderStatus.DISPATCHING
        assert order.printer_slot is None

    async with AsyncSessionLocal() as session:
        board = await session.get(BoardStock, 2)
        assert board.status == BoardStockStatus.RESERVED

        # 프린터는 아직 아무것도 건드리지 않는다.
        for slot in (1, 2, 3):
            printer = await session.get(Printer, slot)
            assert printer.status == PrinterStatus.EMPTY
            assert printer.current_order_id is None


async def test_sqs_produce_failure_rolls_back_board_reservation(monkeypatch):
    await _occupy(2)
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(False))

    async with AsyncSessionLocal() as session:
        with pytest.raises(SqsProduceError):
            await WorkRequestService.create(session, shape=None)

    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(Order))).scalars().one()
        assert order.status == OrderStatus.WAITING
        assert order.printer_slot is None

        board = await session.get(BoardStock, 2)
        assert board.status == BoardStockStatus.OCCUPIED  # RESERVED에서 원복

        tasks = (await session.execute(select(RobotTask))).scalars().all()
        assert tasks == []


async def test_load_success_frees_board_and_dispatches_lowest_empty_printer(monkeypatch):
    await _occupy(2)
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(True))
    monkeypatch.setattr(SqsProducerService, "produce_place_command", _fake_produce(True))

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)

    await WorkRequestService.handle_load_success(order.id)

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order.id)
        assert refreshed.status == OrderStatus.LOADING
        assert refreshed.printer_slot == 1  # 가장 작은 번호의 빈 프린터

        board = await session.get(BoardStock, 2)
        assert board.status == BoardStockStatus.EMPTY

        task = (await session.execute(select(RobotTask))).scalars().one()
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None
        assert task.printer_slot == 1
        assert task.sd_pos_id == 1

        printer = await session.get(Printer, 1)
        assert printer.status == PrinterStatus.RESERVED
        assert printer.current_order_id == order.id


async def test_place_success_starts_printing_with_timer(monkeypatch):
    await _occupy(2)
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(True))
    monkeypatch.setattr(SqsProducerService, "produce_place_command", _fake_produce(True))

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)

    await WorkRequestService.handle_load_success(order.id)
    await WorkRequestService.handle_place_success(order.id)

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order.id)
        assert refreshed.status == OrderStatus.PRINTING
        assert refreshed.started_at is not None

        printer = await session.get(Printer, 1)
        assert printer.status == PrinterStatus.PRINTING
        assert printer.timer_ends_at is not None

        task = (await session.execute(select(RobotTask))).scalars().one()
        assert task.status == TaskStatus.SUCCEEDED
        assert task.finished_at is not None


async def test_place_success_ignores_unknown_work_id():
    await WorkRequestService.handle_place_success(999999)  # 예외 없이 조용히 무시


async def test_load_success_ignores_unknown_work_id():
    await WorkRequestService.handle_load_success(999999)  # 예외 없이 조용히 무시


async def test_load_pick_failed_broadcasts_alert_without_changing_state(monkeypatch):
    await _occupy(2)
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(True))

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)

    await WorkRequestService.handle_load_pick_failed(order.id)

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Order, order.id)
        assert refreshed.status == OrderStatus.DISPATCHING  # 그대로

        board = await session.get(BoardStock, 2)
        assert board.status == BoardStockStatus.RESERVED  # 그대로


async def test_create_defers_load_when_robot_busy_with_another_order(monkeypatch):
    """로봇이 이미 다른 주문의 LOAD1~LOAD2 사이에 있으면, 새 작업요청은 load1을
    보내지 않고 WAITING으로 남는다 — 로봇이 비면(LOAD2 성공) 자동으로 이어서
    디스패치된다."""
    await _occupy(1)
    await _occupy(2)
    sent: list[dict] = []

    async def _fake_produce_load(*, work_id, start_pos_id, retry_token=None):
        sent.append({"work_id": work_id, "start_pos_id": start_pos_id})
        return True

    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce_load)
    monkeypatch.setattr(SqsProducerService, "produce_place_command", _fake_produce(True))

    async with AsyncSessionLocal() as session:
        first = await WorkRequestService.create(session, shape=None)
    assert first.status == OrderStatus.DISPATCHING
    assert sent == [{"work_id": first.id, "start_pos_id": 2}]

    async with AsyncSessionLocal() as session:
        second = await WorkRequestService.create(session, shape=None)

    # 로봇이 아직 첫 주문의 LOAD1~LOAD2 사이라 두 번째는 보류된다 — load1이 추가로
    # 나가지 않고, 적재대도 건드리지 않는다.
    assert second.status == OrderStatus.WAITING
    assert sent == [{"work_id": first.id, "start_pos_id": 2}]
    async with AsyncSessionLocal() as session:
        board1 = await session.get(BoardStock, 1)
        assert board1.status == BoardStockStatus.OCCUPIED  # 예약되지 않음

    # 첫 주문이 LOAD1~LOAD2를 마쳐 로봇이 비면, 밀려 있던 두 번째 주문이 자동으로 이어진다.
    await WorkRequestService.handle_load_success(first.id)
    await WorkRequestService.handle_place_success(first.id)

    assert sent[-1] == {"work_id": second.id, "start_pos_id": 1}
    async with AsyncSessionLocal() as session:
        refreshed_second = await session.get(Order, second.id)
        assert refreshed_second.status == OrderStatus.DISPATCHING


async def test_retry_load_resends_same_start_pos_id(monkeypatch):
    """재시도도 최초 dispatch 때와 같은 start_pos_id(집었던 적재대 슬롯)로 다시 보내야 한다."""
    await _occupy(2)
    sent: list[dict] = []
    tokens: list = []

    async def _fake_produce_load(*, work_id, start_pos_id, retry_token=None):
        sent.append({"work_id": work_id, "start_pos_id": start_pos_id})
        tokens.append(retry_token)
        return True

    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce_load)

    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)

    await WorkRequestService.retry_load(order.id)

    assert sent[-1] == {"work_id": order.id, "start_pos_id": 2}
    assert tokens[0] is None  # 첫 디스패치
    assert tokens[-1]  # 재시도는 FIFO 중복 제거에 걸리지 않게 토큰을 붙여야 한다


async def test_refill_complete_fills_only_empty_slots():
    await _occupy(1)

    async with AsyncSessionLocal() as session:
        rows = await BoardStockService.refill_complete(session)
        by_slot = {r.slot: r.status for r in rows}
        assert by_slot[1] == BoardStockStatus.OCCUPIED  # 이미 채워져 있던 슬롯은 그대로
        assert by_slot[2] == BoardStockStatus.OCCUPIED
        assert by_slot[3] == BoardStockStatus.OCCUPIED

    async with AsyncSessionLocal() as session:
        rows = await BoardStockRepository.list_all(session)
        assert all(r.status == BoardStockStatus.OCCUPIED for r in rows)


def _fake_produce(result: bool):
    async def _produce(*args, **kwargs) -> bool:
        return result

    return _produce


async def _make_print_done_order(monkeypatch) -> int:
    await _occupy(2)
    monkeypatch.setattr(SqsProducerService, "produce_load_command", _fake_produce(True))
    async with AsyncSessionLocal() as session:
        order = await WorkRequestService.create(session, shape=None)
    async with AsyncSessionLocal() as session:
        db_order = await session.get(Order, order.id)
        db_order.status = OrderStatus.PRINT_DONE
        await session.commit()
    return order.id


def _capture_broadcasts(monkeypatch) -> list[tuple]:
    import app.services.work_request_service as wrs

    events: list[tuple] = []
    original = wrs.broadcast_to_web

    async def _spy(session, event_type, data):
        events.append((event_type, data))
        await original(session, event_type, data)

    monkeypatch.setattr(wrs, "broadcast_to_web", _spy)
    return events


def _capture_unload2(monkeypatch, result: bool = True) -> list[dict]:
    sent: list[dict] = []

    async def _fake_unload2(*, work_id, receive_pos_id):
        sent.append({"work_id": work_id, "receive_pos_id": receive_pos_id})
        return result

    monkeypatch.setattr(SqsProducerService, "produce_unload2_command", _fake_unload2)
    return sent


_RECEIVE_POS_STATUS_FOR_ORDER = {
    OrderStatus.UNLOADING: ReceivePosStatus.RESERVED,
    OrderStatus.READY_FOR_PICKUP: ReceivePosStatus.OCCUPIED,
}


async def _set_order(order_id: int, status: OrderStatus, receive_pos_id: int | None) -> None:
    """주문 상태와 그에 맞는 수령대(receive_pos) 행을 함께 맞춘다."""
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id)
        order.status = status
        order.receive_pos_id = receive_pos_id
        pos_status = _RECEIVE_POS_STATUS_FOR_ORDER.get(status)
        if receive_pos_id is not None and pos_status is not None:
            pos = await session.get(ReceivePos, receive_pos_id)
            pos.status = pos_status
            pos.current_order_id = order_id
        await session.commit()


async def _receive_pos_state() -> dict[int, tuple]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(ReceivePos))).scalars().all()
        return {r.pos_id: (r.status, r.current_order_id) for r in rows}


async def test_unload1_success_uses_receive_pos_1_when_all_empty(monkeypatch):
    work_id = await _make_print_done_order(monkeypatch)
    sent = _capture_unload2(monkeypatch)

    assert await WorkRequestService.handle_unload1_success(work_id) is True
    assert sent == [{"work_id": work_id, "receive_pos_id": 1}]

    async with AsyncSessionLocal() as session:
        order = await session.get(Order, work_id)
        assert order.status == OrderStatus.UNLOADING
        assert order.receive_pos_id == 1


@pytest.mark.parametrize(
    "occupied_status, occupied_pos, expected",
    [
        (OrderStatus.READY_FOR_PICKUP, 1, 2),  # 1번에 완성품 대기 중 → 2번
        (OrderStatus.UNLOADING, 1, 2),  # 1번으로 내려놓는 중 → 2번
        (OrderStatus.READY_FOR_PICKUP, 2, 1),  # 2번만 차 있음 → 1번
        (OrderStatus.PICKED_UP, 1, 1),  # 이미 수령해 간 건 점유 아님 → 1번
    ],
)
async def test_unload1_success_picks_free_receive_pos(monkeypatch, occupied_status, occupied_pos, expected):
    other_id = await _make_print_done_order(monkeypatch)
    await _set_order(other_id, occupied_status, occupied_pos)
    work_id = await _make_print_done_order(monkeypatch)
    sent = _capture_unload2(monkeypatch)

    assert await WorkRequestService.handle_unload1_success(work_id) is True
    assert sent == [{"work_id": work_id, "receive_pos_id": expected}]


async def test_unload1_success_does_not_send_when_receive_pos_full(monkeypatch):
    for pos in (1, 2):
        other_id = await _make_print_done_order(monkeypatch)
        await _set_order(other_id, OrderStatus.READY_FOR_PICKUP, pos)
    work_id = await _make_print_done_order(monkeypatch)
    sent = _capture_unload2(monkeypatch)

    events = _capture_broadcasts(monkeypatch)

    assert await WorkRequestService.handle_unload1_success(work_id) is False
    assert sent == []
    assert ("alert.receive_pos_full", {"work_id": work_id, "reason": "RECEIVE_POS_FULL"}) in events
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, work_id)
        assert order.status == OrderStatus.UNLOADING  # 로봇이 들고 대기 중
        assert order.receive_pos_id is None


async def test_unload1_success_keeps_waiting_on_produce_failure(monkeypatch):
    work_id = await _make_print_done_order(monkeypatch)
    _capture_unload2(monkeypatch, result=False)

    assert await WorkRequestService.handle_unload1_success(work_id) is False
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, work_id)
        assert order.status == OrderStatus.UNLOADING
        assert order.receive_pos_id is None  # 배정 롤백 → 다음 수령하기 때 재시도 대상


async def test_unload1_success_releases_printer(monkeypatch):
    work_id = await _make_print_done_order(monkeypatch)
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, work_id)
        order.printer_slot = 2
        printer = await session.get(Printer, 2)
        printer.status = PrinterStatus.DONE
        printer.current_order_id = work_id
        await session.commit()
    _capture_unload2(monkeypatch)

    await WorkRequestService.handle_unload1_success(work_id)

    async with AsyncSessionLocal() as session:
        printer = await session.get(Printer, 2)
        assert printer.status == PrinterStatus.EMPTY
        assert printer.current_order_id is None


async def test_pickup_resumes_waiting_unload2(monkeypatch):
    """수령대 가득 참 → 대기 → 사람이 수령하기 → 빈 자리로 unload2 자동 발행."""
    occupant_ids = []
    for pos in (1, 2):
        other_id = await _make_print_done_order(monkeypatch)
        await _set_order(other_id, OrderStatus.READY_FOR_PICKUP, pos)
        occupant_ids.append(other_id)
    work_id = await _make_print_done_order(monkeypatch)
    sent = _capture_unload2(monkeypatch)
    await WorkRequestService.handle_unload1_success(work_id)
    assert sent == []

    async with AsyncSessionLocal() as session:
        await OrderService.pick_up(session, occupant_ids[1])  # 2번 수령대 비움

    assert sent == [{"work_id": work_id, "receive_pos_id": 2}]
    async with AsyncSessionLocal() as session:
        assert (await session.get(Order, work_id)).receive_pos_id == 2


async def test_pickup_without_waiting_order_sends_nothing(monkeypatch):
    other_id = await _make_print_done_order(monkeypatch)
    await _set_order(other_id, OrderStatus.READY_FOR_PICKUP, 1)
    sent = _capture_unload2(monkeypatch)

    async with AsyncSessionLocal() as session:
        await OrderService.pick_up(session, other_id)

    assert sent == []


async def test_retry_unload1_resends_with_retry_token(monkeypatch):
    work_id = await _make_print_done_order(monkeypatch)
    async with AsyncSessionLocal() as session:
        db_order = await session.get(Order, work_id)
        db_order.printer_slot = 1
        await session.commit()
    sent: list[dict] = []

    async def _fake_unload1(*, work_id, sd_pos_id, retry_token=None):
        sent.append({"work_id": work_id, "sd_pos_id": sd_pos_id, "retry_token": retry_token})
        return True

    monkeypatch.setattr(SqsProducerService, "produce_unload_command", _fake_unload1)

    await WorkRequestService.retry_unload1(work_id)

    assert sent[0]["work_id"] == work_id and sent[0]["sd_pos_id"] == 1
    assert sent[0]["retry_token"]


async def test_retry_unload1_rejects_order_not_print_done():
    with pytest.raises(UnloadRetryNotFoundError):
        await WorkRequestService.retry_unload1(999999)


async def test_retry_dedup_id_differs_from_first_send(monkeypatch):
    """재전송이 첫 전송과 같은 MessageDeduplicationId를 쓰면 FIFO 큐가 버린다."""
    dedup_ids: list[str] = []

    async def _fake_send_raw(*, message_group_id, dedup_id, body, log_extra):
        dedup_ids.append(dedup_id)
        return True

    monkeypatch.setattr(SqsProducerService, "_send_raw", _fake_send_raw)
    await SqsProducerService.produce_unload_command(work_id=7, sd_pos_id=3)
    await SqsProducerService.produce_unload_command(work_id=7, sd_pos_id=3, retry_token="abc")

    assert dedup_ids[0] == "unload-7"
    assert dedup_ids[1] == "unload-7-abc"


async def test_unload2_success_marks_ready_for_pickup(monkeypatch):
    work_id = await _make_print_done_order(monkeypatch)
    _capture_unload2(monkeypatch)
    await WorkRequestService.handle_unload1_success(work_id)

    await WorkRequestService.handle_unload2_success(work_id)

    async with AsyncSessionLocal() as session:
        order = await session.get(Order, work_id)
        assert order.status == OrderStatus.READY_FOR_PICKUP
        assert order.ready_at is not None
        assert order.receive_pos_id == 1


async def test_unload1_success_ignores_order_not_print_done(monkeypatch):
    sent: list = []

    async def _fake_unload2(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(SqsProducerService, "produce_unload2_command", _fake_unload2)

    assert await WorkRequestService.handle_unload1_success(999999) is False
    assert sent == []


async def test_unload1_failed_broadcasts_alert_without_changing_state(monkeypatch):
    work_id = await _make_print_done_order(monkeypatch)
    events: list[tuple] = []

    async def _fake_broadcast(session, event_type, data):
        events.append((event_type, data))

    import app.services.work_request_service as wrs

    monkeypatch.setattr(wrs, "broadcast_to_web", _fake_broadcast)

    await WorkRequestService.handle_unload1_failed(work_id)

    assert events == [("alert.unload_pick_failed", {"work_id": work_id, "reason": "UNLOAD_PICK_FAILED"})]
    async with AsyncSessionLocal() as session:
        assert (await session.get(Order, work_id)).status == OrderStatus.PRINT_DONE


async def test_receive_pos_table_lifecycle(monkeypatch):
    """수령대 테이블: EMPTY → RESERVED(unload2 발행) → OCCUPIED(success_unload2) → EMPTY(수령하기)."""
    work_id = await _make_print_done_order(monkeypatch)
    _capture_unload2(monkeypatch)
    assert await _receive_pos_state() == {1: (ReceivePosStatus.EMPTY, None), 2: (ReceivePosStatus.EMPTY, None)}

    await WorkRequestService.handle_unload1_success(work_id)
    assert (await _receive_pos_state())[1] == (ReceivePosStatus.RESERVED, work_id)

    await WorkRequestService.handle_unload2_success(work_id)
    assert (await _receive_pos_state())[1] == (ReceivePosStatus.OCCUPIED, work_id)

    async with AsyncSessionLocal() as session:
        await OrderService.pick_up(session, work_id)
    assert (await _receive_pos_state())[1] == (ReceivePosStatus.EMPTY, None)

    async with AsyncSessionLocal() as session:
        assert (await session.get(Order, work_id)).receive_pos_id == 1  # 이력은 주문에 남는다


async def test_receive_pos_rolls_back_on_produce_failure(monkeypatch):
    work_id = await _make_print_done_order(monkeypatch)
    _capture_unload2(monkeypatch, result=False)

    await WorkRequestService.handle_unload1_success(work_id)

    assert (await _receive_pos_state())[1] == (ReceivePosStatus.EMPTY, None)
