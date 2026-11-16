"""
3Farm 로봇 액션 서버 노드 (robot_action_server).

sfarm_bridge가 보내는 /sfarm/load, /sfarm/unload 액션 goal을 받아
motions.py의 run_load() / run_unload()를 실행하고 feedback/result를 돌려준다.

이 파일은 ROS 연결(액션 수신, feedback/result, 로봇 초기화)만 담당한다.
  - 구체적인 동작 : motions.py
  - 좌표          : poses.py

ros2 run sfarm_robot robot_action_server
"""
from __future__ import annotations

import threading

import DR_init
import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node


from sfarm_interfaces.action import Load1, Load2, Unload


ROBOT_ID = 'dsr01'
ROBOT_MODEL = 'm0609'

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


# ---------------------------------------------------------------- 액션 서버
class RobotActionServer(Node):


    """/sfarm/load, /sfarm/load2, /sfarm/unload 액션을 받아 로봇 동작을 실행하는 노드."""

    def __init__(self, run_load1, run_unload, run_load2=None) -> None:
        super().__init__('sfarm_robot_action_server')
        self.run_load1 = run_load1
        self.run_unload = run_unload
        self.run_load2 = run_load2
        self.cb_group = ReentrantCallbackGroup()
        # 로봇은 한 번에 하나의 동작만 수행
        self.busy_lock = threading.Lock()
        self.stop_requested = threading.Event()

        self.load_server = ActionServer(
            self, Load1, '/sfarm/load',
            execute_callback=self.execute_load,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )

        self.load2_server = ActionServer(
            self, Load2, '/sfarm/load2',
            execute_callback=self.execute_load2,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )
        self.unload_server = ActionServer(
            self, Unload, '/sfarm/unload',
            execute_callback=self.execute_unload,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )

        self.get_logger().info('ready: /sfarm/load, /sfarm/load2, /sfarm/unload')

    def goal_callback(self, goal_request) -> GoalResponse:
        """로봇이 다른 동작 중이면 goal을 거절한다."""
        if self.busy_lock.locked():
            self.get_logger().warning(
                f'robot busy; rejecting goal work_id={goal_request.work_id}'
            )
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle) -> CancelResponse:
        """로봇 동작 도중 취소는 지원하지 않는다."""
        return CancelResponse.REJECT

    def execute_load1(self, goal_handle):
        """Load1 콜백."""
        self.stop_requested.clear()
        return self._execute(
            goal_handle, Load1, None, self.run_load1, 'load1'
        )

    def execute_load(self, goal_handle):
        """Load 콜백."""
        return self._execute(
            goal_handle, Load1, Load1.Result.WORK_TYPE_LOAD, self.run_load1, 'load'
        )

    def execute_load2(self, goal_handle):
        """Load2 콜백 (빼기 -> 작업대 sd_pos_id층)."""
        return self._execute(goal_handle, Load2, None, self.run_load2, 'load2')

    def execute_unload(self, goal_handle):
        """Unload 콜백."""
        return self._execute(
            goal_handle, Unload, Unload.Result.WORK_TYPE_UNLOAD, self.run_unload, 'unload'
        )

    def _populate_pose_feedback(self, feedback) -> None:
        """Load1 등 posj/posx 필드를 가진 feedback에 현재 로봇 좌표를 채운다."""
        if not hasattr(feedback, 'posj') or not hasattr(feedback, 'posx'):
            return
        if self.get_current_poses is None:
            return
        try:
            posj_vals, posx_vals = self.get_current_poses()
            feedback.posj = posj_vals
            feedback.posx = posx_vals
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f'failed to read current pose: {exc}')

    def _execute(self, goal_handle, action_type, work_type, sequence, name):
        goal = goal_handle.request
        result = action_type.Result()
        result.work_id = goal.work_id
        if work_type is not None and hasattr(result, 'work_type'):
            result.work_type = work_type

        feedback = action_type.Feedback()
        feedback.work_id = goal.work_id
        feedback.start_at = self.get_clock().now().to_msg()

        with self.busy_lock:
            self.get_logger().info(f'[{name}] start: {goal}')
            self._populate_pose_feedback(feedback)
            goal_handle.publish_feedback(feedback)
            try:
                # True(또는 None)=성공, False=실패(예: 무게 감지 안 됨)
                ok = sequence(goal, log=self.get_logger().info)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().error(f'[{name}] failed: {exc}')
                feedback.end_at = self.get_clock().now().to_msg()
                self._populate_pose_feedback(feedback)
                goal_handle.publish_feedback(feedback)
                goal_handle.abort()
                result.success = False
                if hasattr(result, 'message'):
                    result.message = f'{name} failed: {exc}'
                return result

        feedback.end_at = self.get_clock().now().to_msg()
        self._populate_pose_feedback(feedback)
        goal_handle.publish_feedback(feedback)
        result.success = ok is not False
        if result.success:
            goal_handle.succeed()
            if hasattr(result, 'message'):
                result.message = f'{name} done'
        else:
            goal_handle.abort()
            if hasattr(result, 'message'):
                result.message = f'{name} failed: weight not detected (gripping failed)'
        self.get_logger().info(
            f'[{name}] done: work_id={goal.work_id} success={result.success}'
        )
        return result


def main(args=None) -> None:
    """Entry point for robot_action_server node."""
    rclpy.init(args=args)

    # DSR_ROBOT2는 내부에서 이 노드로 spin_until_future_complete를 하므로
    # executor에 넣지 않는 별도 노드로 둔다.
    dsr_node = rclpy.create_node('sfarm_robot_dsr', namespace=ROBOT_ID)
    DR_init.__dsr__node = dsr_node
    try:
        # motions.py는 맨 위에서 DSR_ROBOT2를 import 하므로 DR_init 설정이 끝난 지금 import 한다.

        from sfarm_robot.motions import run_load, run_load2, run_unload
    except ImportError as e:
        dsr_node.get_logger().error(f'Error importing DSR_ROBOT2 / motions: {e}')
        dsr_node.destroy_node()
        rclpy.shutdown()
        return


    node = RobotActionServer(run_load, run_unload, run_load2=run_load2)
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        dsr_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
