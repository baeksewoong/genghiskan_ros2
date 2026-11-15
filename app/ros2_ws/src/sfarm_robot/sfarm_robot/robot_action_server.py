"""
3Farm 로봇 액션 서버 노드 (robot_action_server).

sfarm_bridge가 보내는 /sfarm/load, /sfarm/unload 액션 goal을 받아
Doosan 로봇(DSR_ROBOT2)으로 동작을 수행하고 결과를 돌려준다.

현재는 테스트용으로 시작 위치 <-> X축 +257.73mm 위치를 왕복하는 간단한 동작만 한다.
  - Load   : 3D 프린터에 넣는 동작   -> run_load()   를 수정
  - Unload : 프린터에서 빼는 동작     -> run_unload() 를 수정
  - 좌표            : 아래 "좌표" 섹션의 J_* / X_* 상수를 수정

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

from sfarm_interfaces.action import Load, Unload

ROBOT_ID = 'dsr01'
ROBOT_MODEL = 'm0609'

VELJ, ACCJ = 30.0, 30.0
VELX, ACCX = 100.0, 100.0

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

# ---------------------------------------------------------------- 좌표
# 좌표는 여기서 수정한다. (posj: 관절각 [deg], posx: 위치[mm] + 자세[deg])
# 1. 시작 위치 (이동 전)
J_START = [-0.01, 0.03, 90.00, 0.04, 90.00, 0.02]
X_START = [367.47, 7.02, 424.12, 117.75, 179.93, 117.69]
# 2. X축 이동 후 위치 (+257.73mm 이동)
J_TARGET = [0.04, 41.68, 31.85, -0.10, 106.47, -0.02]
X_TARGET = [625.20, 6.99, 424.72, 90.29, 179.98, 90.20]

# DSR_ROBOT2 함수들 (main()에서 DSR 전용 노드를 만든 뒤 import 해서 채운다)
dsr = {}


# ---------------------------------------------------------------- 동작 시퀀스
def move_round_trip() -> None:
    """시작 위치 -> 목표 위치 -> 시작 위치 왕복 (테스트용)."""
    movej, posj = dsr['movej'], dsr['posj']
    movej(posj(*J_START), vel=VELJ, acc=ACCJ)
    movej(posj(*J_TARGET), vel=VELJ, acc=ACCJ)
    movej(posj(*J_START), vel=VELJ, acc=ACCJ)


def run_load(goal: Load.Goal) -> None:
    """Load 동작: 3D 프린터에 넣기.

    goal.start_pos_id(가져올 위치), goal.pos_3d_id(넣을 프린터)에 따라
    좌표를 골라 movej/movel 하도록 여기를 수정하면 된다.
    """
    move_round_trip()


def run_unload(goal: Unload.Goal) -> None:
    """Unload 동작: 3D 프린터에서 빼서 놓기.

    goal.pos_3d_id(뺄 프린터), goal.receive_pos_id(놓을 위치)에 따라
    좌표를 골라 movej/movel 하도록 여기를 수정하면 된다.
    """
    move_round_trip()


# ---------------------------------------------------------------- 액션 서버
class RobotActionServer(Node):
    """/sfarm/load, /sfarm/unload 액션을 받아 로봇 동작을 실행하는 노드."""

    def __init__(self) -> None:
        super().__init__('sfarm_robot_action_server')
        self.cb_group = ReentrantCallbackGroup()
        # 로봇은 한 번에 하나의 동작만 수행
        self.busy_lock = threading.Lock()

        self.load_server = ActionServer(
            self, Load, '/sfarm/load',
            execute_callback=self.execute_load,
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
        self.get_logger().info('ready: /sfarm/load, /sfarm/unload')

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

    def execute_load(self, goal_handle):
        """Load 콜백."""
        return self._execute(
            goal_handle, Load, Load.Result.WORK_TYPE_LOAD, run_load, 'load'
        )

    def execute_unload(self, goal_handle):
        """Unload 콜백."""
        return self._execute(
            goal_handle, Unload, Unload.Result.WORK_TYPE_UNLOAD, run_unload, 'unload'
        )

    def _execute(self, goal_handle, action_type, work_type, sequence, name):
        goal = goal_handle.request
        result = action_type.Result()
        result.work_id = goal.work_id
        result.work_type = work_type

        feedback = action_type.Feedback()
        feedback.work_id = goal.work_id
        feedback.start_at = self.get_clock().now().to_msg()

        with self.busy_lock:
            self.get_logger().info(f'[{name}] start: {goal}')
            goal_handle.publish_feedback(feedback)
            try:
                sequence(goal)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().error(f'[{name}] failed: {exc}')
                feedback.end_at = self.get_clock().now().to_msg()
                goal_handle.publish_feedback(feedback)
                goal_handle.abort()
                result.success = False
                result.message = f'{name} failed: {exc}'
                return result

        feedback.end_at = self.get_clock().now().to_msg()
        goal_handle.publish_feedback(feedback)
        goal_handle.succeed()
        result.success = True
        result.message = f'{name} done'
        self.get_logger().info(f'[{name}] done: work_id={goal.work_id}')
        return result


def main(args=None) -> None:
    """Entry point for robot_action_server node."""
    rclpy.init(args=args)

    # DSR_ROBOT2는 내부에서 이 노드로 spin_until_future_complete를 하므로
    # executor에 넣지 않는 별도 노드로 둔다.
    dsr_node = rclpy.create_node('sfarm_robot_dsr', namespace=ROBOT_ID)
    DR_init.__dsr__node = dsr_node
    try:
        from DSR_ROBOT2 import movej, movel
        from DR_common2 import posj, posx
    except ImportError as e:
        dsr_node.get_logger().error(f'Error importing DSR_ROBOT2: {e}')
        rclpy.shutdown()
        return
    dsr.update(movej=movej, movel=movel, posj=posj, posx=posx)

    node = RobotActionServer()
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
