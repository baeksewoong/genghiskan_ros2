# Copyright 2026 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for sfarm_bridge SQS event payload formatting."""

from datetime import datetime
import threading
from unittest.mock import MagicMock

from sfarm_bridge.sfarm_bridge import (
    build_action_result_event,
    build_load1_result_event,
    build_load2_result_event,
    build_robot_event,
    build_unload1_result_event,
    build_unload2_result_event,
    DEFAULT_EVENT_QUEUE_URL,
    parse_task_command,
    SqsEchoNode,
)
from sfarm_interfaces.action import Load, Load1, Load2, Unload1, Unload2


def test_default_event_queue_url():
    """Verify default robot-events SQS queue URL."""
    assert DEFAULT_EVENT_QUEUE_URL == (
        'https://sqs.ap-northeast-2.amazonaws.com/135135392043/robot-events'
    )


def test_build_robot_event_load_format():
    """Verify LOAD command produces the expected robot-events payload."""
    command = {
        'type': 'LOAD',
        'command_id': 'test-load-001',
        'job_id': 'job-001',
        'printer_id': 2,
    }
    event = build_robot_event(command, 'robot-arm-1')

    assert set(event.keys()) == {
        'event_id',
        'event_type',
        'command_id',
        'job_id',
        'robot_id',
        'printer_id',
        'reason',
        'occurred_at',
    }
    assert event['event_id'].startswith('evt-')
    assert event['event_type'] == 'LOAD_COMPLETED'
    assert event['command_id'] == 'test-load-001'
    assert event['job_id'] == 'job-001'
    assert event['robot_id'] == 'robot-arm-1'
    assert event['printer_id'] == 2
    assert isinstance(event['printer_id'], int)
    assert event['reason'] is None
    assert event['occurred_at'].endswith('+00:00')
    parsed_dt = datetime.fromisoformat(event['occurred_at'])
    assert parsed_dt.tzinfo is not None


def test_build_robot_event_variants():
    """Verify command_type fallback, string printer_id, and REJECTED."""
    unload_cmd = {
        'command_type': 'unload',
        'command_id': 'cmd-002',
        'job_id': 'job-002',
        'printer_id': '3',
        'robot_id': 'robot-arm-2',
    }
    unload_evt = build_robot_event(unload_cmd, 'robot-arm-1')
    assert unload_evt['event_type'] == 'UNLOAD_COMPLETED'
    assert unload_evt['printer_id'] == 3
    assert unload_evt['robot_id'] == 'robot-arm-2'
    assert unload_evt['reason'] is None

    bad_cmd = {'type': 'UNKNOWN', 'command_id': 'cmd-003'}
    bad_evt = build_robot_event(bad_cmd, 'robot-arm-1')
    assert bad_evt['event_type'] == 'REJECTED'
    assert bad_evt['reason'] == 'unknown type'


def test_parse_task_command_load_and_unload():
    """Verify SQS load/unload payloads parse into ROS 2 action goals."""
    load_cmd = {'work_id': 16, 'start_pos_id': 3, 'sd_pos_id': 2}
    kind, fields = parse_task_command(load_cmd)
    assert kind == 'LOAD'
    assert fields == {'work_id': 16, 'start_pos_id': 3, 'sd_pos_id': 2}

    load_min_cmd = {'type': 'load1', 'work_id': 179, 'start_pos_id': 3}
    kind_min, fields_min = parse_task_command(load_min_cmd)
    assert kind_min == 'LOAD'
    assert fields_min == {'work_id': 179, 'start_pos_id': 3, 'sd_pos_id': None}

    load2_cmd = {'type': 'load2', 'work_id': 179, 'sd_pos_id': 2}
    kind_l2, fields_l2 = parse_task_command(load2_cmd)
    assert kind_l2 == 'LOAD2'
    assert fields_l2 == {'work_id': 179, 'sd_pos_id': 2}

    unload1_cmd = {'type': 'unload1', 'work_id': 180, 'sd_pos_id': 2}
    kind_u1, fields_u1 = parse_task_command(unload1_cmd)
    assert kind_u1 == 'UNLOAD1'
    assert fields_u1 == {'work_id': 180, 'sd_pos_id': 2}

    unload2_cmd = {'type': 'unload2', 'work_id': 181, 'receive_pos_id': 1}
    kind_u2, fields_u2 = parse_task_command(unload2_cmd)
    assert kind_u2 == 'UNLOAD2'
    assert fields_u2 == {'work_id': 181, 'receive_pos_id': 1}

    unload2_typo_cmd = {'type': 'unload2', 'work_id': 182, 'recieve_pos_id': 2}
    kind_u2_t, fields_u2_t = parse_task_command(unload2_typo_cmd)
    assert kind_u2_t == 'UNLOAD2'
    assert fields_u2_t == {'work_id': 182, 'receive_pos_id': 2}

    assert parse_task_command({'type': 'unload2', 'work_id': 183}) == (None, None)

    unload_cmd = {'work_id': 17, 'sd_pos_id': 2, 'receive_pos_id': 1}
    kind2, fields2 = parse_task_command(unload_cmd)
    assert kind2 == 'UNLOAD'
    assert fields2 == {'work_id': 17, 'pos_3d_id': 2, 'receive_pos_id': 1}


def test_build_action_result_event():
    """Verify ROS 2 action result converts to robot-events SQS payload."""
    evt = build_action_result_event(
        action_kind='LOAD',
        work_id=16,
        success=True,
        message='done',
        work_type=Load.Result.WORK_TYPE_LOAD,
        robot_id='robot-arm-1',
    )
    assert evt['event_type'] == 'LOAD_COMPLETED'
    assert evt['work_id'] == 16
    assert evt['work_type'] == 'load'
    assert evt['success'] is True
    assert evt['message'] == 'done'


def test_build_load1_result_events():
    """Verify unified Load1 success and failure SQS event payloads."""
    ok_evt = build_load1_result_event(work_id=42, success=True)
    assert ok_evt == {'type': 'success_load1', 'work_id': 42}
    assert 'stage' not in ok_evt
    assert 'status' not in ok_evt

    fail_evt = build_load1_result_event(work_id=42, success=False)
    assert fail_evt == {'type': 'fail_load1', 'work_id': 42}
    assert 'stage' not in fail_evt
    assert 'status' not in fail_evt


def test_handle_load1_result_success_and_failure():
    """Verify Load1 result callback sends unified SQS payload and stop srv on failure."""
    fake_node = MagicMock()
    fake_node.produce.return_value = True

    ok_res = Load1.Result()
    ok_res.work_id = 42
    ok_res.success = True

    assert SqsEchoNode.handle_load1_result(fake_node, ok_res, 42, sd_pos_id=2) is True
    assert fake_node.produce.call_args[0][0] == {
        'type': 'success_load1',
        'work_id': 42,
    }
    fake_node.on_load1_success.assert_called_once_with(42, 2)
    fake_node.call_load_stop_service.assert_not_called()

    fake_node.reset_mock()
    fake_node.produce.return_value = True

    fail_res = Load1.Result()
    fail_res.work_id = 43
    fail_res.success = False

    assert SqsEchoNode.handle_load1_result(fake_node, fail_res, 43, sd_pos_id=1) is True
    fake_node.call_load_stop_service.assert_called_once_with(
        error_type='fail_load1',
        work_id=43,
        stage='load1',
    )
    assert fake_node.produce.call_args[0][0] == {
        'type': 'fail_load1',
        'work_id': 43,
    }


def test_build_load2_result_events():
    """Verify unified Load2 success and failure SQS event payloads."""
    assert build_load2_result_event(work_id=179, success=True) == {
        'type': 'success_load2',
        'work_id': 179,
    }
    assert build_load2_result_event(work_id=179, success=False) == {
        'type': 'fail_load2',
        'work_id': 179,
    }


def test_handle_load2_result_success_and_failure():
    """Verify Load2 result callback sends unified SQS payload and stop srv on failure."""
    fake_node = MagicMock()
    fake_node.produce.return_value = True

    ok_res = Load2.Result()
    ok_res.work_id = 179
    ok_res.success = True

    assert SqsEchoNode.handle_load2_result(fake_node, ok_res, 179) is True
    assert fake_node.produce.call_args[0][0] == {
        'type': 'success_load2',
        'work_id': 179,
    }
    fake_node.call_load_stop_service.assert_not_called()

    fake_node.reset_mock()
    fake_node.produce.return_value = True

    fail_res = Load2.Result()
    fail_res.work_id = 179
    fail_res.success = False

    assert SqsEchoNode.handle_load2_result(fake_node, fail_res, 179) is True
    fake_node.call_load_stop_service.assert_called_once_with(
        error_type='fail_load2',
        work_id=179,
        stage='load2',
    )
    assert fake_node.produce.call_args[0][0] == {
        'type': 'fail_load2',
        'work_id': 179,
    }


def test_handle_message_load1_and_load2_dispatch():
    """Verify SQS LOAD1 and LOAD2 messages dispatch real ROS 2 actions."""
    fake_node = MagicMock()
    res1 = Load1.Result(work_id=179, success=True)
    fake_node.execute_load1.return_value = (res1, True)
    msg1 = {
        'MessageId': 'msg-179-1',
        'ReceiptHandle': 'rh-179-1',
        'Body': '{"work_id": 179, "start_pos_id": 3}',
    }

    SqsEchoNode.handle_message(fake_node, msg1)

    fake_node.execute_load1.assert_called_once_with(
        work_id=179,
        start_pos_id=3,
        sd_pos_id=None,
    )
    fake_node.delete.assert_called_once_with(msg1)

    fake_node.reset_mock()
    res2 = Load2.Result(work_id=179, success=True)
    fake_node.execute_load2.return_value = (res2, True)
    msg2 = {
        'MessageId': 'msg-179-2',
        'ReceiptHandle': 'rh-179-2',
        'Body': '{"type": "load2", "work_id": 179, "sd_pos_id": 2}',
    }

    SqsEchoNode.handle_message(fake_node, msg2)

    fake_node.execute_load2.assert_called_once_with(work_id=179, sd_pos_id=2)
    fake_node.delete.assert_called_once_with(msg2)


def test_build_and_handle_unload1_result():
    """Verify Unload1 SQS payloads, result callback, and handle_message dispatch."""
    assert build_unload1_result_event(work_id=180, success=True) == {
        'type': 'success_unload1',
        'work_id': 180,
    }
    assert build_unload1_result_event(work_id=180, success=False) == {
        'type': 'fail_unload1',
        'work_id': 180,
    }

    fake_node = MagicMock()
    fake_node.produce.return_value = True

    ok_res = Unload1.Result()
    ok_res.work_id = 180
    ok_res.success = True
    assert SqsEchoNode.handle_unload1_result(fake_node, ok_res, 180) is True
    assert fake_node.produce.call_args[0][0] == {
        'type': 'success_unload1',
        'work_id': 180,
    }
    fake_node.on_unload1_success.assert_called_once_with(180)
    fake_node.call_load_stop_service.assert_not_called()

    fake_node.reset_mock()
    fake_node.produce.return_value = True

    fail_res = Unload1.Result()
    fail_res.work_id = 180
    fail_res.success = False
    assert SqsEchoNode.handle_unload1_result(fake_node, fail_res, 180) is True
    fake_node.call_load_stop_service.assert_called_once_with(
        error_type='fail_unload1',
        work_id=180,
        stage='unload1',
    )
    assert fake_node.produce.call_args[0][0] == {
        'type': 'fail_unload1',
        'work_id': 180,
    }

    fake_node.reset_mock()
    fake_node.execute_unload1.return_value = (ok_res, True)
    msg_u1 = {
        'MessageId': 'msg-180',
        'ReceiptHandle': 'rh-180',
        'Body': '{"type": "unload1", "work_id": 180, "sd_pos_id": 2}',
    }
    SqsEchoNode.handle_message(fake_node, msg_u1)
    fake_node.execute_unload1.assert_called_once_with(work_id=180, sd_pos_id=2)
    fake_node.delete.assert_called_once_with(msg_u1)


def test_build_and_handle_unload2_result():
    """Verify Unload2 SQS payloads, result callback, and handle_message dispatch."""
    assert build_unload2_result_event(work_id=181, success=True) == {
        'type': 'success_unload2',
        'work_id': 181,
    }
    assert build_unload2_result_event(work_id=181, success=False) == {
        'type': 'fail_unload2',
        'work_id': 181,
    }

    fake_node = MagicMock()
    fake_node.produce.return_value = True

    ok_res = Unload2.Result()
    ok_res.work_id = 181
    ok_res.success = True
    assert SqsEchoNode.handle_unload2_result(fake_node, ok_res, 181) is True
    assert fake_node.produce.call_args[0][0] == {
        'type': 'success_unload2',
        'work_id': 181,
    }
    fake_node.call_load_stop_service.assert_not_called()

    fake_node.reset_mock()
    fake_node.produce.return_value = True

    fail_res = Unload2.Result()
    fail_res.work_id = 181
    fail_res.success = False
    assert SqsEchoNode.handle_unload2_result(fake_node, fail_res, 181) is True
    fake_node.call_load_stop_service.assert_called_once_with(
        error_type='fail_unload2',
        work_id=181,
        stage='unload2',
    )
    assert fake_node.produce.call_args[0][0] == {
        'type': 'fail_unload2',
        'work_id': 181,
    }

    goal_u2 = Unload2.Goal(work_id=181, receive_pos_id=1)
    assert goal_u2.work_id == 181
    assert goal_u2.receive_pos_id == 1

    fake_node.reset_mock()
    fake_node.execute_unload2.return_value = (ok_res, True)
    msg_u2 = {
        'MessageId': 'msg-181',
        'ReceiptHandle': 'rh-181',
        'Body': '{"type": "unload2", "work_id": 181, "receive_pos_id": 1}',
    }
    SqsEchoNode.handle_message(fake_node, msg_u2)
    fake_node.execute_unload2.assert_called_once_with(work_id=181, receive_pos_id=1)
    fake_node.delete.assert_called_once_with(msg_u2)


def test_robot_busy_blocks_sqs_polling_and_dispatch(monkeypatch):
    """Verify sfarm_bridge does not poll SQS or dispatch/produce while robot is busy."""
    fake_node = _make_bundle_test_node()

    assert SqsEchoNode._try_acquire_robot_busy(fake_node, '/sfarm/load1') is True
    assert SqsEchoNode._is_robot_busy(fake_node) is True
    assert SqsEchoNode._try_acquire_robot_busy(fake_node, '/sfarm/load2') is False

    # handle_message must defer without dispatching or producing SQS while busy
    msg = {
        'MessageId': 'msg-busy',
        'ReceiptHandle': 'rh-busy',
        'Body': '{"type": "UNKNOWN"}',
    }
    assert SqsEchoNode.handle_message(fake_node, msg) is False
    fake_node.produce.assert_not_called()
    fake_node.delete.assert_not_called()

    # consume_loop must not call sqs.receive_message while robot is busy
    fake_node.stop = threading.Event()
    fake_node.stop.wait = MagicMock(side_effect=lambda _t: fake_node.stop.set())
    monkeypatch.setattr('sfarm_bridge.sfarm_bridge.rclpy.ok', lambda: True)
    SqsEchoNode.consume_loop(fake_node)
    fake_node.sqs.receive_message.assert_not_called()

    # on_load1_result clears busy flag BEFORE calling handle_load1_result (which produces SQS)
    was_busy_during_handle = []
    fake_node.handle_load1_result.side_effect = (
        lambda *_args: was_busy_during_handle.append(SqsEchoNode._is_robot_busy(fake_node))
        or True
    )
    res_future = MagicMock()
    res_future.result.return_value.result = Load1.Result(work_id=77, success=True)
    done_event = threading.Event()
    holder = {'result': None, 'event_sent': False}
    SqsEchoNode.on_load1_result(fake_node, res_future, done_event, holder, 77, None)

    assert done_event.is_set()
    assert was_busy_during_handle == [False]
    assert SqsEchoNode._is_robot_busy(fake_node) is False
    assert holder['event_sent'] is True


def test_execute_load1_clears_busy_on_reject_and_keeps_busy_on_timeout():
    """Verify _robot_busy clears on rejection and stays set on action timeout."""
    fake_node = _make_bundle_test_node()
    fake_node.action_timeout_sec = 0.0
    fake_node.stop = threading.Event()
    fake_node._wait_for_action_done.side_effect = (
        lambda name, evt: SqsEchoNode._wait_for_action_done(fake_node, name, evt)
    )

    # Goal rejected clears _robot_busy
    goal_future = MagicMock()
    goal_future.result.return_value.accepted = False
    assert SqsEchoNode._try_acquire_robot_busy(fake_node, '/sfarm/load1') is True
    done_event = threading.Event()
    SqsEchoNode.on_load1_goal_response(fake_node, goal_future, done_event, {}, 10, None)
    assert done_event.is_set()
    assert SqsEchoNode._is_robot_busy(fake_node) is False

    # Action timeout leaves _robot_busy set until on_load1_result completes
    fake_node.load1_client.wait_for_server.return_value = True
    fake_node.load1_client.send_goal_async.return_value = MagicMock()
    res, sent = SqsEchoNode.execute_load1(fake_node, work_id=11, start_pos_id=3)
    assert (res, sent) == (None, False)
    assert SqsEchoNode._is_robot_busy(fake_node) is True


def _make_bundle_test_node():
    """Create a MagicMock bridge node wired with real busy/bundle state helpers."""
    fake_node = MagicMock()
    fake_node._robot_busy_lock = threading.Lock()
    fake_node._robot_busy_event = threading.Event()
    fake_node._active_action_name = None
    fake_node._active_bundle = None
    fake_node._is_robot_busy.side_effect = lambda: SqsEchoNode._is_robot_busy(fake_node)
    fake_node._get_active_bundle.side_effect = (
        lambda: SqsEchoNode._get_active_bundle(fake_node)
    )
    fake_node._is_command_allowed_in_bundle.side_effect = (
        lambda kind, wid: SqsEchoNode._is_command_allowed_in_bundle(fake_node, kind, wid)
    )
    fake_node._try_acquire_robot_busy.side_effect = (
        lambda name, bundle_action=None, work_id=None: SqsEchoNode._try_acquire_robot_busy(
            fake_node, name, bundle_action=bundle_action, work_id=work_id
        )
    )
    fake_node._clear_robot_busy.side_effect = (
        lambda clear_bundle=True: SqsEchoNode._clear_robot_busy(
            fake_node, clear_bundle=clear_bundle
        )
    )
    return fake_node


def test_load_bundle_blocks_other_commands_until_load2_completes():
    """Verify load1+load2 acts as one bundle blocking unrelated commands in between."""
    fake_node = _make_bundle_test_node()
    fake_node.handle_load1_result.return_value = True
    fake_node.handle_load2_result.return_value = True

    # Start load1 for work_id=42 -> bundle ('LOAD', 42) active, then load1 succeeds
    assert SqsEchoNode._try_acquire_robot_busy(
        fake_node, '/sfarm/load1', bundle_action='LOAD', work_id=42
    ) is True
    res_l1 = MagicMock()
    res_l1.result.return_value.result = Load1.Result(work_id=42, success=True)
    SqsEchoNode.on_load1_result(fake_node, res_l1, threading.Event(), {}, 42, None)

    assert SqsEchoNode._is_robot_busy(fake_node) is False
    assert SqsEchoNode._get_active_bundle(fake_node) == ('LOAD', 42)

    # Between load1 and load2, other commands (JOG, other LOAD, UNLOAD1, wrong LOAD2) are blocked
    for body in (
        '{"type": "JOG", "jog_id": "j1", "space": "TASK", "axis": "X", '
        '"direction": 1, "step_size": 5}',
        '{"work_id": 43, "start_pos_id": 3}',
        '{"type": "unload1", "work_id": 42, "sd_pos_id": 3}',
        '{"type": "load2", "work_id": 43, "sd_pos_id": 2}',
        '{"type": "UNKNOWN"}',
    ):
        msg = {'MessageId': 'm', 'ReceiptHandle': 'rh', 'Body': body}
        assert SqsEchoNode.handle_message(fake_node, msg) is False

    fake_node.execute_jog.assert_not_called()
    fake_node.execute_load1.assert_not_called()
    fake_node.execute_unload1.assert_not_called()
    fake_node.execute_load2.assert_not_called()
    fake_node.produce.assert_not_called()
    fake_node.delete.assert_not_called()

    # Matching load2 for work_id=42 is allowed and closes the bundle on completion
    fake_node.execute_load2.return_value = (Load2.Result(work_id=42, success=True), True)
    msg_l2 = {
        'MessageId': 'm-l2',
        'ReceiptHandle': 'rh-l2',
        'Body': '{"type": "load2", "work_id": 42, "sd_pos_id": 2}',
    }
    assert SqsEchoNode.handle_message(fake_node, msg_l2) is True
    fake_node.execute_load2.assert_called_once_with(work_id=42, sd_pos_id=2)
    fake_node.delete.assert_called_once_with(msg_l2)

    assert SqsEchoNode._try_acquire_robot_busy(
        fake_node, '/sfarm/load2', bundle_action='LOAD2', work_id=42
    ) is True
    res_l2 = MagicMock()
    res_l2.result.return_value.result = Load2.Result(work_id=42, success=True)
    SqsEchoNode.on_load2_result(fake_node, res_l2, threading.Event(), {}, 42)
    assert SqsEchoNode._get_active_bundle(fake_node) is None


def test_unload_bundle_blocks_other_commands_until_unload2_completes():
    """Verify unload1+unload2 acts as one bundle blocking unrelated commands in between."""
    fake_node = _make_bundle_test_node()
    fake_node.handle_unload1_result.return_value = True
    fake_node.handle_unload2_result.return_value = True

    assert SqsEchoNode._try_acquire_robot_busy(
        fake_node, '/sfarm/unload1', bundle_action='UNLOAD1', work_id=55
    ) is True
    res_u1 = MagicMock()
    res_u1.result.return_value.result = Unload1.Result(work_id=55, success=True)
    SqsEchoNode.on_unload1_result(fake_node, res_u1, threading.Event(), {}, 55)

    assert SqsEchoNode._get_active_bundle(fake_node) == ('UNLOAD', 55)

    for body in (
        '{"work_id": 56, "start_pos_id": 3}',
        '{"type": "GRIPPER", "gripper_cmd_id": "g1", "action": "OPEN"}',
        '{"type": "unload2", "work_id": 56, "receive_pos_id": 1}',
    ):
        msg = {'MessageId': 'm', 'ReceiptHandle': 'rh', 'Body': body}
        assert SqsEchoNode.handle_message(fake_node, msg) is False

    fake_node.execute_unload2.return_value = (Unload2.Result(work_id=55, success=True), True)
    msg_u2 = {
        'MessageId': 'm-u2',
        'ReceiptHandle': 'rh-u2',
        'Body': '{"type": "unload2", "work_id": 55, "receive_pos_id": 1}',
    }
    assert SqsEchoNode.handle_message(fake_node, msg_u2) is True
    fake_node.execute_unload2.assert_called_once_with(work_id=55, receive_pos_id=1)

    assert SqsEchoNode._try_acquire_robot_busy(
        fake_node, '/sfarm/unload2', bundle_action='UNLOAD2', work_id=55
    ) is True
    res_u2 = MagicMock()
    res_u2.result.return_value.result = Unload2.Result(work_id=55, success=True)
    SqsEchoNode.on_unload2_result(fake_node, res_u2, threading.Event(), {}, 55)
    assert SqsEchoNode._get_active_bundle(fake_node) is None


def test_load1_failure_clears_bundle_for_retry():
    """Verify failed load1 clears active bundle so retry-load can run."""
    fake_node = _make_bundle_test_node()
    fake_node.handle_load1_result.return_value = True

    assert SqsEchoNode._try_acquire_robot_busy(
        fake_node, '/sfarm/load1', bundle_action='LOAD', work_id=66
    ) is True
    res_fail = MagicMock()
    res_fail.result.return_value.result = Load1.Result(work_id=66, success=False)
    SqsEchoNode.on_load1_result(fake_node, res_fail, threading.Event(), {}, 66, None)

    assert SqsEchoNode._get_active_bundle(fake_node) is None
