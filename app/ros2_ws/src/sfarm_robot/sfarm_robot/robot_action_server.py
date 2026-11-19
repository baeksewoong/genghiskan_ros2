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


from sfarm_interfaces.action import (
    Gripper,
    Jog,
    Load,
    Load1,
    Load2,
    Unload,
    Unload1,
    Unload2,
)
from sfarm_interfaces.srv import Error, JogStop


ROBOT_ID = 'dsr01'
ROBOT_MODEL = 'm0609'

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


# ---------------------------------------------------------------- 액션 서버
class RobotActionServer(Node):
    """/sfarm/load1, /sfarm/load2, /sfarm/unload1, /sfarm/unload2, /sfarm/load, /sfarm/unload 액션과 정지 서비스 노드."""

    def __init__(
        self,
        run_load,
        run_unload,
        run_load1=None,
        run_load2=None,
        run_unload1=None,
        run_unload2=None,
        run_jog=None,
        run_gripper=None,
        stop_motion=None,
        get_current_poses=None,
    ) -> None:
        super().__init__('sfarm_robot_action_server')
        self.run_load = run_load
        self.run_load1 = run_load1
        self.run_load2 = run_load2
        self.run_unload = run_unload
        self.run_unload1 = run_unload1
        self.run_unload2 = run_unload2
        self.run_jog = run_jog
        self.run_gripper = run_gripper
        # /sfarm/jog/stop 서비스가 motions.py를 거치지 않고 직접 호출하는 stop(DR_SSTOP)
        # 콜러블 (PRD 5.3). DSR_ROBOT2는 DR_init 설정 뒤에만 import 가능해서 main()에서
        # 주입받는다 (run_load 등과 같은 패턴).
        self.stop_motion = stop_motion
        self.get_current_poses = get_current_poses
        self.cb_group = ReentrantCallbackGroup()
        # 로봇은 한 번에 하나의 동작만 수행
        self.busy_lock = threading.Lock()
        self.stop_requested = threading.Event()
        # goal_callback이 로봇 busy라고 거절할 때가 아니라, busy_lock을 잡은 동안
        # 실제로 어떤 동작이 진행 중인지 추적한다. /sfarm/jog/stop이 "지금 멈춰도
        # 되는 동작인지"(jog/gripper만) 판단하는 데 쓴다 (PRD 4.1/5.3).
        self.current_action: str | None = None

        self.load1_server = ActionServer(
            self, Load1, '/sfarm/load1',
            execute_callback=self.execute_load1,
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
        self.unload1_server = ActionServer(
            self, Unload1, '/sfarm/unload1',
            execute_callback=self.execute_unload1,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )
        self.unload2_server = ActionServer(
            self, Unload2, '/sfarm/unload2',
            execute_callback=self.execute_unload2,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )
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
        self.jog_server = ActionServer(
            self, Jog, '/sfarm/jog',
            execute_callback=self.execute_jog,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )
        self.gripper_server = ActionServer(
            self, Gripper, '/sfarm/gripper',
            execute_callback=self.execute_gripper,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.cb_group,
        )
        self.load_stop_srv = self.create_service(
            Error,
            '/sfarm/load/stop',
            self.handle_load_stop_service,
            callback_group=self.cb_group,
        )
        self.jog_stop_srv = self.create_service(
            JogStop,
            '/sfarm/jog/stop',
            self.handle_jog_stop_service,
            callback_group=self.cb_group,
        )

        self.get_logger().info(
            'ready: /sfarm/load1, /sfarm/load2, /sfarm/unload1, /sfarm/unload2, '
            '/sfarm/load, /sfarm/unload, /sfarm/jog, /sfarm/gripper, '
            '/sfarm/load/stop, /sfarm/jog/stop'
        )

    def handle_load_stop_service(
        self, request: Error.Request, response: Error.Response
    ) -> Error.Response:
        """브릿지에서 전달된 정지/에러 서비스 요청을 기록하고 응답한다."""
        self.stop_requested.set()
        self.get_logger().error(
            f'[/sfarm/load/stop] type={request.type} work_id={request.work_id} '
            f'stage={request.stage} message={request.message}'
        )
        response.success = True
        response.message = (
            f'stop acknowledged (stage={request.stage}, work_id={request.work_id})'
        )
        return response

    def handle_jog_stop_service(
        self, request: JogStop.Request, response: JogStop.Response
    ) -> JogStop.Response:
        """조그/그리퍼 세션 중일 때만 stop(DR_SSTOP)을 시도한다 (PRD 5.3).

        LOAD/UNLOAD 중에는 아무것도 하지 않고 success=True, stopped_motion=False로
        응답한다 - _insert_move/_wiggle_side/insert_sd 등 기존 LOAD/UNLOAD 안전
        시퀀스(걸림 감지, task_compliance_ctrl/release_compliance_ctrl 짝 맞추기)를
        이 STOP이 침범하지 않도록 스코프를 좁힌 것이 이 설계의 핵심 안전 판단이다.
        """
        if self.current_action not in ('jog', 'gripper'):
            response.success = True
            response.stopped_motion = False
            response.message = (
                '지금 로봇이 조그/그리퍼 동작 중이 아님'
                if self.current_action is None
                else f'로봇이 {self.current_action} 중이라 조그 정지 요청은 무시함'
            )
            self.get_logger().info(f'[/sfarm/jog/stop] {response.message} (reason={request.reason})')
            return response
        if self.stop_motion is None:
            response.success = False
            response.stopped_motion = False
            response.message = 'stop_motion 콜러블이 주입되지 않음 (서버 초기화 문제)'
            self.get_logger().error(f'[/sfarm/jog/stop] {response.message}')
            return response
        try:
            self.stop_motion()
            response.success = True
            response.stopped_motion = True
            response.message = 'stop(DR_SSTOP) 호출함'
            self.get_logger().warning(f'[/sfarm/jog/stop] {response.message} (reason={request.reason})')
        except Exception as exc:  # noqa: BLE001
            response.success = False
            response.stopped_motion = False
            response.message = f'stop() 호출 실패: {exc}'
            self.get_logger().error(f'[/sfarm/jog/stop] {response.message}')
        return response

    def goal_callback(self, goal_request) -> GoalResponse:
        """로봇이 다른 동작 중이면 goal을 거절한다.

        Jog/Gripper goal에는 work_id가 없으므로(PRD 4.1), 로그용 식별자는
        work_id/jog_id/gripper_cmd_id 중 있는 것을 쓴다.
        """
        if self.busy_lock.locked():
            goal_id = (
                getattr(goal_request, 'work_id', None)
                or getattr(goal_request, 'jog_id', None)
                or getattr(goal_request, 'gripper_cmd_id', None)
            )
            self.get_logger().warning(f'robot busy; rejecting goal id={goal_id}')
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

    def execute_load2(self, goal_handle):
        """Load2 콜백 (빼기 -> 작업대 sd_pos_id층)."""
        self.stop_requested.clear()
        return self._execute(goal_handle, Load2, None, self.run_load2, 'load2')

    def execute_unload1(self, goal_handle):
        """Unload1 콜백."""
        self.stop_requested.clear()
        return self._execute(goal_handle, Unload1, None, self.run_unload1, 'unload1')

    def execute_unload2(self, goal_handle):
        """Unload2 콜백 (빼내기 -> 수령대 receive_pos_id -> 홈 복귀)."""
        self.stop_requested.clear()
        return self._execute(goal_handle, Unload2, None, self.run_unload2, 'unload2')

    def execute_load(self, goal_handle):
        """Load 콜백."""
        return self._execute(
            goal_handle, Load, Load.Result.WORK_TYPE_LOAD, self.run_load, 'load'
        )

    def execute_unload(self, goal_handle):
        """Unload 콜백."""
        return self._execute(
            goal_handle, Unload, Unload.Result.WORK_TYPE_UNLOAD, self.run_unload, 'unload'
        )

    def execute_jog(self, goal_handle):
        """Jog 콜백 (PRD 4.1). work_id가 없으므로 _execute()를 재사용하지 않고
        jog_id 전용으로 복제한 버전 - 안전 동작 패턴(busy_lock, current_action,
        feedback start/end)은 _execute()와 동일하다."""
        goal = goal_handle.request
        result = Jog.Result(jog_id=goal.jog_id)
        feedback = Jog.Feedback(jog_id=goal.jog_id, start_at=self.get_clock().now().to_msg())
        with self.busy_lock:
            self.current_action = 'jog'
            self.get_logger().info(f'[jog] start: {goal}')
            goal_handle.publish_feedback(feedback)
            try:
                ok, posj_vals, posx_vals = self.run_jog(goal, log=self.get_logger().info)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().error(f'[jog] failed: {exc}')
                feedback.end_at = self.get_clock().now().to_msg()
                goal_handle.publish_feedback(feedback)
                goal_handle.abort()
                result.success, result.message = False, f'jog failed: {exc}'
                return result
            finally:
                self.current_action = None
        feedback.end_at = self.get_clock().now().to_msg()
        goal_handle.publish_feedback(feedback)
        result.success = ok is not False
        result.posj, result.posx = posj_vals, posx_vals
        if result.success:
            goal_handle.succeed()
            result.message = 'jog done'
        else:
            goal_handle.abort()
            result.message = 'jog failed: not reachable or step limit exceeded'
        self.get_logger().info(f'[jog] done: jog_id={goal.jog_id} success={result.success}')
        return result

    def execute_gripper(self, goal_handle):
        """Gripper 콜백 (PRD 4.1). execute_jog와 같은 모양, run_gripper는
        posj/posx 없이 (ok, state)만 돌려준다."""
        goal = goal_handle.request
        result = Gripper.Result(gripper_cmd_id=goal.gripper_cmd_id)
        feedback = Gripper.Feedback(
            gripper_cmd_id=goal.gripper_cmd_id, start_at=self.get_clock().now().to_msg()
        )
        with self.busy_lock:
            self.current_action = 'gripper'
            self.get_logger().info(f'[gripper] start: {goal}')
            goal_handle.publish_feedback(feedback)
            try:
                ok, state = self.run_gripper(goal, log=self.get_logger().info)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().error(f'[gripper] failed: {exc}')
                feedback.end_at = self.get_clock().now().to_msg()
                goal_handle.publish_feedback(feedback)
                goal_handle.abort()
                result.success, result.message = False, f'gripper failed: {exc}'
                return result
            finally:
                self.current_action = None
        feedback.end_at = self.get_clock().now().to_msg()
        goal_handle.publish_feedback(feedback)
        result.success = ok is not False
        result.state = state
        if result.success:
            goal_handle.succeed()
            result.message = 'gripper done'
        else:
            goal_handle.abort()
            result.message = 'gripper failed'
        self.get_logger().info(
            f'[gripper] done: gripper_cmd_id={goal.gripper_cmd_id} success={result.success}'
        )
        return result

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
            self.current_action = name
            try:
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
            finally:
                self.current_action = None

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
    stop_node = rclpy.create_node('sfarm_robot_stop', namespace=ROBOT_ID)
    DR_init.__dsr__node = dsr_node
    try:
        # motions.py는 맨 위에서 DSR_ROBOT2를 import 하므로 DR_init 설정이 끝난 지금 import 한다.

        from sfarm_robot.motions import (
            get_current_poses,
            run_gripper,
            run_jog,
            run_load,
            run_load1,
            run_load2,
            run_unload,
            run_unload1,
            run_unload2,
        )
        # stop(DR_SSTOP)은 motions.py의 run_*()를 거치지 않고 /sfarm/jog/stop
        # 서비스가 직접 호출한다 (PRD 5.3) - busy_lock을 안 잡은 상태에서 호출돼야
        # 하므로 여기서 콜러블로만 주입한다. DSR_ROBOT2는 DR_init 설정이 끝난 지금만
        # import 가능하다.
        # DSR_ROBOT2.py에는 DRL의 stop()에 대응하는 Python wrapper가 없어
        # motion/move_stop 서비스를 직접 호출한다.
        # run_jog()가 dsr_node를 spin하는 동안에도 /sfarm/jog/stop이 충돌 없이
        # 서비스를 호출할 수 있도록 전용 stop_node와 락을 사용한다.
        import DSR_ROBOT2
        from DSR_ROBOT2 import DR_SSTOP
        from dsr_msgs2.srv import MoveStop

        srv_prefix = getattr(DSR_ROBOT2, '_srv_name_prefix', 'dsr_controller2/')
        move_stop_client = stop_node.create_client(
            MoveStop, f'{srv_prefix}motion/move_stop'
        )
        stop_lock = threading.Lock()

        def stop_motion() -> None:
            with stop_lock:
                if not move_stop_client.wait_for_service(timeout_sec=1.0):
                    raise RuntimeError('motion/move_stop 서비스에 연결할 수 없음')
                req = MoveStop.Request()
                req.stop_mode = DR_SSTOP
                future = move_stop_client.call_async(req)
                rclpy.spin_until_future_complete(stop_node, future, timeout_sec=3.0)
                if not future.done():
                    raise TimeoutError('motion/move_stop 서비스 응답 타임아웃')
                res = future.result()
                if res is None or not res.success:
                    raise RuntimeError(f'motion/move_stop 호출 실패: {res}')
    except ImportError as e:
        dsr_node.get_logger().error(f'Error importing DSR_ROBOT2 / motions: {e}')
        stop_node.destroy_node()
        dsr_node.destroy_node()
        rclpy.shutdown()
        return

    node = RobotActionServer(
        run_load,
        run_unload,
        run_load1=run_load1,
        run_load2=run_load2,
        run_unload1=run_unload1,
        run_unload2=run_unload2,
        run_jog=run_jog,
        run_gripper=run_gripper,
        stop_motion=stop_motion,
        get_current_poses=get_current_poses,
    )
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        stop_node.destroy_node()
        dsr_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
