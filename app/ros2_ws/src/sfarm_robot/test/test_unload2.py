"""Unit and ROS 2 action tests for Unload2 in sfarm_robot."""
from __future__ import annotations

import importlib
import sys
import threading
import types
from unittest.mock import MagicMock

import pytest
import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor

from sfarm_interfaces.action import Unload2


def _import_motions_with_mock_dsr(monkeypatch):
    """Import sfarm_robot.motions with mocked DR_common2 / DSR_ROBOT2."""
    dr_common = types.ModuleType('DR_common2')
    dr_common.posj = lambda *args: ('posj', args)
    dr_common.posx = lambda *args: ('posx', args)

    dsr_robot = types.ModuleType('DSR_ROBOT2')
    call_log = []

    def movej(pose, vel=0.0, acc=0.0):
        call_log.append(('movej', pose, vel, acc))

    def movel(pose, vel=0.0, acc=0.0):
        call_log.append(('movel', pose, vel, acc))

    def fkin(pose, ref=None):
        return [100.0, 200.0, 300.0, 0.0, 90.0, 0.0]

    def set_digital_output(pin, val):
        call_log.append(('set_digital_output', pin, val))

    def wait(sec):
        call_log.append(('wait', sec))

    dsr_robot.DR_AXIS_Z = 'DR_AXIS_Z'
    dsr_robot.DR_BASE = 'DR_BASE'
    dsr_robot.OFF = 0
    dsr_robot.ON = 1
    dsr_robot.align_axis = MagicMock()
    dsr_robot.fkin = fkin
    dsr_robot.get_current_posj = MagicMock(return_value=[0.0] * 6)
    dsr_robot.get_current_posx = MagicMock(return_value=([0.0] * 6,))
    dsr_robot.get_tool_force = MagicMock(return_value=[0.0] * 6)
    dsr_robot.movej = movej
    dsr_robot.movel = movel
    dsr_robot.release_compliance_ctrl = MagicMock()
    dsr_robot.set_digital_output = set_digital_output
    dsr_robot.task_compliance_ctrl = MagicMock()
    dsr_robot.wait = wait

    dr_init = types.ModuleType('DR_init')
    dr_init.__dsr__id = 'dsr01'
    dr_init.__dsr__model = 'm0609'
    dr_init.__dsr__node = None

    monkeypatch.setitem(sys.modules, 'DR_common2', dr_common)
    monkeypatch.setitem(sys.modules, 'DSR_ROBOT2', dsr_robot)
    monkeypatch.setitem(sys.modules, 'DR_init', dr_init)

    sys.modules.pop('sfarm_robot.motions', None)
    motions = importlib.import_module('sfarm_robot.motions')
    return motions, call_log


def test_run_unload2_sequence_recv1_and_recv2(monkeypatch):
    """Verify run_unload2 executes extract steps, receive pos, grip_open, and return."""
    motions, call_log = _import_motions_with_mock_dsr(monkeypatch)
    motions._last_unload_layer = 3

    for recv_id in (1, 2):
        call_log.clear()
        goal = Unload2.Goal(work_id=181, receive_pos_id=recv_id)
        assert motions.run_unload2(goal) is True

        # Extract steps 7, 8, 9 use movej; steps 10, 11 use movel (UNLOAD_MOVEL_FROM_STEP=10)
        move_ops = [entry[0] for entry in call_log if entry[0] in ('movej', 'movel')]
        # 3 extract movej + 2 extract movel + 2 recv movel + 4 return movel = 11 moves
        assert move_ops[:5] == ['movej', 'movej', 'movej', 'movel', 'movel']
        assert all(op == 'movel' for op in move_ops[5:])
        assert len(move_ops) == 11

        # Verify grip_open() is called after reaching receive_pos and before return moves
        open_idx = call_log.index(('set_digital_output', 1, 0))
        assert ('set_digital_output', 2, 1) in call_log[open_idx:open_idx + 3]
        moves_before_open = [
            e[0] for e in call_log[:open_idx] if e[0] in ('movej', 'movel')
        ]
        moves_after_open = [
            e[0] for e in call_log[open_idx:] if e[0] in ('movej', 'movel')
        ]
        assert len(moves_before_open) == 7
        assert len(moves_after_open) == 4


def test_run_unload2_validation_and_fallback(monkeypatch):
    """Verify validation on invalid receive_pos_id / missing layer and single-layer fallback."""
    motions, call_log = _import_motions_with_mock_dsr(monkeypatch)

    # Single-layer fallback when _last_unload_layer is None
    motions._last_unload_layer = None
    assert motions.run_unload2(Unload2.Goal(work_id=182, receive_pos_id=1)) is True
    assert len(call_log) > 0

    # Invalid receive_pos_id fails before moving
    call_log.clear()
    with pytest.raises(ValueError, match='UNLOAD_RECV_J'):
        motions.run_unload2(Unload2.Goal(work_id=183, receive_pos_id=9))
    assert call_log == []

    # Layer without extract steps fails before moving
    motions._last_unload_layer = 2
    with pytest.raises(ValueError, match='UNLOAD_EXTRACT_STEPS'):
        motions.run_unload2(Unload2.Goal(work_id=184, receive_pos_id=1))
    assert call_log == []


def test_robot_action_server_unload2_ros2_action(monkeypatch):
    """Verify RobotActionServer exposes /sfarm/unload2 and returns result + feedback."""
    motions, _ = _import_motions_with_mock_dsr(monkeypatch)
    sys.modules.pop('sfarm_robot.robot_action_server', None)
    ras = importlib.import_module('sfarm_robot.robot_action_server')

    rclpy.init()
    received_feedback = []
    server_node = None
    client_node = None
    executor = None
    spin_thread = None

    try:
        server_node = ras.RobotActionServer(
            run_load=lambda g, log=print: True,
            run_unload=lambda g, log=print: True,
            run_unload2=motions.run_unload2,
        )
        client_node = rclpy.create_node('test_unload2_client')
        client = ActionClient(client_node, Unload2, '/sfarm/unload2')

        executor = MultiThreadedExecutor()
        executor.add_node(server_node)
        executor.add_node(client_node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        assert client.wait_for_server(timeout_sec=5.0)

        goal = Unload2.Goal(work_id=202, receive_pos_id=2)
        goal_future = client.send_goal_async(
            goal,
            feedback_callback=lambda msg: received_feedback.append(msg.feedback),
        )
        done = threading.Event()
        holder = {}

        def _on_goal(fut):
            gh = fut.result()
            holder['accepted'] = gh.accepted
            res_fut = gh.get_result_async()
            res_fut.add_done_callback(lambda rf: (holder.update(res=rf.result().result), done.set()))

        goal_future.add_done_callback(_on_goal)
        assert done.wait(timeout=10.0)
        assert holder['accepted'] is True
        assert holder['res'].work_id == 202
        assert holder['res'].success is True
        assert len(received_feedback) == 2
        assert all(fb.work_id == 202 for fb in received_feedback)
    finally:
        if executor is not None:
            executor.shutdown()
        if client_node is not None:
            client_node.destroy_node()
        if server_node is not None:
            server_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if spin_thread is not None:
            spin_thread.join(timeout=2.0)
