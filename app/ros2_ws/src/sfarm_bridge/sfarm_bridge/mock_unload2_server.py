"""Mock ROS 2 action server for testing /sfarm/unload2 without physical hardware."""
from __future__ import annotations

import threading
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node

from sfarm_interfaces.action import Unload2
from sfarm_interfaces.srv import Error


class MockUnload2Server(Node):
    """Mock /sfarm/unload2 action server and /sfarm/load/stop service."""

    def __init__(self) -> None:
        super().__init__('mock_unload2_server')
        self.success = bool(self.declare_parameter('success', True).value)
        self.delay_sec = float(self.declare_parameter('delay_sec', 1.0).value)

        self.cb_group = ReentrantCallbackGroup()
        self.busy_lock = threading.Lock()

        self.unload2_server = ActionServer(
            self,
            Unload2,
            '/sfarm/unload2',
            execute_callback=self.execute_unload2,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )
        self.stop_srv = self.create_service(
            Error,
            '/sfarm/load/stop',
            self.handle_stop_service,
            callback_group=self.cb_group,
        )
        self.get_logger().info(
            f'Mock /sfarm/unload2 server ready '
            f'(success={self.success}, delay_sec={self.delay_sec})'
        )

    def goal_callback(self, goal_request: Unload2.Goal) -> GoalResponse:
        """Accept incoming Unload2 goals when idle."""
        if self.busy_lock.locked():
            self.get_logger().warning(
                f'busy; rejecting work_id={goal_request.work_id}'
            )
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle) -> CancelResponse:
        """Reject cancel requests to match robot_action_server behavior."""
        return CancelResponse.REJECT

    def handle_stop_service(
        self, request: Error.Request, response: Error.Response
    ) -> Error.Response:
        """Acknowledge /sfarm/load/stop calls during failure tests."""
        self.get_logger().warning(
            f'[MOCK /sfarm/load/stop] type={request.type} '
            f'work_id={request.work_id} stage={request.stage} '
            f'message={request.message}'
        )
        response.success = True
        response.message = (
            f'mock stop acknowledged (stage={request.stage}, work_id={request.work_id})'
        )
        return response

    def execute_unload2(self, goal_handle) -> Unload2.Result:
        """Simulate Unload2 execution and return configured success/failure."""
        goal = goal_handle.request
        result = Unload2.Result()
        result.work_id = goal.work_id

        feedback = Unload2.Feedback()
        feedback.work_id = goal.work_id
        feedback.start_at = self.get_clock().now().to_msg()

        with self.busy_lock:
            self.get_logger().info(
                f'[MOCK /sfarm/unload2] start: '
                f'work_id={goal.work_id}, receive_pos_id={goal.receive_pos_id}'
            )
            goal_handle.publish_feedback(feedback)
            if self.delay_sec > 0.0:
                time.sleep(self.delay_sec)

        feedback.end_at = self.get_clock().now().to_msg()
        goal_handle.publish_feedback(feedback)

        result.success = self.success
        if result.success:
            goal_handle.succeed()
        else:
            goal_handle.abort()

        self.get_logger().info(
            f'[MOCK /sfarm/unload2] done: '
            f'work_id={goal.work_id}, receive_pos_id={goal.receive_pos_id}, '
            f'success={result.success}'
        )
        return result


def main(args=None) -> None:
    """Entry point for mock_unload2_server node."""
    rclpy.init(args=args)
    node = MockUnload2Server()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
