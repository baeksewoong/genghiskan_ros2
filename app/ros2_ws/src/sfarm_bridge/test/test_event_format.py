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
from unittest.mock import MagicMock

from sfarm_bridge.sfarm_bridge import (
    build_action_result_event,
    build_load_fail_event,
    build_pick_complete_event,
    build_robot_event,
    DEFAULT_EVENT_QUEUE_URL,
    parse_task_command,
    SqsEchoNode,
)
from sfarm_interfaces.action import Load, Load1
from sfarm_interfaces.srv import Error


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
    assert fields == {'work_id': 16, 'start_pos_id': 3, 'pos_3d_id': 2}

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


def test_build_pick_complete_and_fail_load1_events():
    """Verify Load1 success and failure SQS event payloads."""
    pick_evt = build_pick_complete_event(work_id=42, robot_id='robot-arm-1')
    assert pick_evt['work_id'] == 42
    assert pick_evt['status'] == 'pick_complete'
    assert pick_evt['robot_id'] == 'robot-arm-1'
    assert pick_evt['event_id'].startswith('evt-')

    fail_evt = build_load_fail_event(
        stage=Error.Request.STAGE_LOAD1,
        work_id=42,
        robot_id='robot-arm-1',
        message='weight check failed',
    )
    assert fail_evt['type'] == 'fail_load1'
    assert fail_evt['work_id'] == 42
    assert fail_evt['stage'] == 'load1'
    assert fail_evt['success'] is False
    assert fail_evt['message'] == 'weight check failed'


def test_handle_load1_result_success_and_failure():
    """Verify Load1 result callback triggers pick_complete or stop srv + fail_load1."""
    fake_node = MagicMock()
    fake_node.robot_id = 'robot-arm-1'
    fake_node.produce.return_value = True

    ok_res = Load1.Result()
    ok_res.work_id = 42
    ok_res.success = True
    ok_res.message = 'ok'

    assert SqsEchoNode.handle_load1_result(fake_node, ok_res, 42, sd_pos_id=2) is True
    produced_ok = fake_node.produce.call_args[0][0]
    assert produced_ok['status'] == 'pick_complete'
    assert produced_ok['work_id'] == 42
    fake_node.on_load1_success.assert_called_once_with(42, 2)
    fake_node.call_load_stop_service.assert_not_called()

    fake_node.reset_mock()
    fake_node.produce.return_value = True

    fail_res = Load1.Result()
    fail_res.work_id = 43
    fail_res.success = False
    fail_res.message = 'underweight'

    assert SqsEchoNode.handle_load1_result(fake_node, fail_res, 43, sd_pos_id=1) is True
    fake_node.call_load_stop_service.assert_called_once_with(
        error_type='fail_load1',
        work_id=43,
        stage='load1',
        message='underweight',
    )
    produced_fail = fake_node.produce.call_args[0][0]
    assert produced_fail['type'] == 'fail_load1'
    assert produced_fail['work_id'] == 43
    assert produced_fail['stage'] == 'load1'
