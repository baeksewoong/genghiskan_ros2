"""
로봇 팔 조인트 상태를 실시간으로 백엔드 WebSocket에 스트리밍하는 노드.

두산 로봇 드라이버가 publish하는 표준 sensor_msgs/msg/JointState(`/joint_states`)를
"구독만" 하고(subscribe-only - 기존 sfarm_bridge/sfarm_robot/sfarm_interfaces 패키지는
건드리지 않는다), joint_1..joint_6 각도를 기본 10Hz로 스로틀링해 백엔드 WebSocket
엔드포인트(`/ws/robot-state`)로 전송한다. 티칭팬던트 페이지의 3D 로봇팔 뷰어가 이
프레임을 받아 실제 로봇 자세를 실시간으로 반영한다 (ROS2/백엔드/프론트엔드 공통
통신 규격).

ros2 run sfarm_joint_streamer joint_streamer --ros-args \
  -p backend_ws_url:=ws://localhost:8000/ws/robot-state \
  -p ws_token:=<TOKEN>

주의:
  - /joint_states에 그리퍼(RG2) 조인트가 섞여 있어도 joint_1..joint_6 이름에
    해당하지 않으면 무시한다.
  - 실제 조인트 이름이 다르게 들어오면(예: prefix) joint_name_prefix 또는
    joint_name_overrides 파라미터로 매핑을 조정한다 (아래 _build_source_names 참고).
  - RG2 그리퍼는 /joint_states에 조인트가 없고 컨트롤박스 디지털 출력(DO1=닫기,
    DO2=열기, sfarm_robot.motions.grip_close/grip_open)으로 제어된다. 그래서 두산
    드라이버의 io/get_ctrl_box_digital_output 서비스를 주기적으로 조회해 열림/닫힘을
    판정하고, payload의 gripper.width_mm(열림=110, 닫힘=1 기본 - 보드 두께)로 실어 보낸다.
    서비스가 없거나(드라이버 미기동, dsr_msgs2 미설치) 상태가 모호하면 gripper 필드를
    생략한다 -> 프론트 뷰어는 마지막 폭을 유지한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import quote

import rclpy
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile

from sensor_msgs.msg import JointState

try:
    from dsr_msgs2.srv import GetCtrlBoxDigitalOutput
except ImportError:  # pragma: no cover - 두산 메시지 패키지가 없어도 조인트 스트리밍은 동작
    GetCtrlBoxDigitalOutput = None

try:
    import websocket  # websocket-client (pip: websocket-client, import: websocket)
except ImportError:  # pragma: no cover - 설치 안 됐을 때도 노드 자체는 죽지 않게
    websocket = None


DEFAULT_JOINT_NAMES = ['joint_1', 'joint_2', 'joint_3', 'joint_4', 'joint_5', 'joint_6']
# 백엔드/프론트엔드와 확정된 통신 규격상 고정 필드 - 패키지 이름이 sfarm_joint_streamer여도
# 계약에 쓰인 값 그대로 보낸다(임의로 바꾸지 않음).
PAYLOAD_SOURCE = 'ros2_sfarm_bridge'
ANGLE_UNIT = 'rad'
GRIPPER_TYPE = 'rg2'


def load_dotenv() -> None:
    """.env 파일을 찾아 os.environ에 setdefault (sfarm_bridge.py의 load_dotenv()와 동일 패턴)."""
    candidates = [Path.cwd() / '.env']
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / '.env')
        candidates.append(parent / 'src' / 'sfarm_joint_streamer' / '.env')

    for env_path in candidates:
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding='utf-8').splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
        break


def _parse_name_list(value) -> list[str]:
    """ROS 파라미터(list) 또는 환경변수(comma-separated string)에서 문자열 리스트를 만든다."""
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(',') if v.strip()]
    return []


def _parse_overrides(value: str) -> dict[str, str]:
    """'joint_1=dsr_j1,joint_2=dsr_j2' 형태 문자열을 {'joint_1': 'dsr_j1', ...}로 변환."""
    overrides: dict[str, str] = {}
    for item in _parse_name_list(value):
        if '=' not in item:
            continue
        key, _, actual = item.partition('=')
        key = key.strip()
        actual = actual.strip()
        if key and actual:
            overrides[key] = actual
    return overrides


class WebSocketSender:
    """백엔드 WebSocket에 JSON 프레임을 보내는, 재연결을 전담하는 백그라운드 스레드.

    타이머 콜백(rclpy 콜백 스레드)을 블로킹하지 않도록, 실제 송신은 이 클래스가 갖는
    별도 데몬 스레드에서만 수행한다. 콜백 쪽은 enqueue_latest()로 '최신 1개'만 남기고
    즉시 반환한다 - 라이브 조인트 상태 스트림이라 연결이 느리거나 끊겼을 때 밀린 과거
    프레임을 쌓아서 다 보내려 하지 않는다(최신 값만 중요).
    """

    def __init__(
        self,
        node: Node,
        url: str,
        log_url: str,
        connect_timeout_sec: float,
        reconnect_min_sec: float,
        reconnect_max_sec: float,
    ) -> None:
        self._node = node
        self._url = url
        self._log_url = log_url  # 토큰이 빠진, 로그에 찍어도 되는 URL
        self._connect_timeout_sec = connect_timeout_sec
        self._reconnect_min_sec = max(0.1, reconnect_min_sec)
        self._reconnect_max_sec = max(self._reconnect_min_sec, reconnect_max_sec)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict | None = None
        self._has_pending = threading.Event()
        self._ws = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._has_pending.set()  # _send_loop의 wait()를 깨워서 종료 체크하게 함
        with self._lock:
            ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._thread.join(timeout=2.0)

    def enqueue_latest(self, payload: dict) -> None:
        """최신 payload로 교체한다 (밀린 이전 프레임은 버림)."""
        with self._lock:
            self._pending = payload
        self._has_pending.set()

    def _run(self) -> None:
        if websocket is None:
            self._node.get_logger().error(
                "'websocket-client' 패키지가 설치되어 있지 않아 WebSocket 전송을 "
                '시작할 수 없습니다 (pip install websocket-client). '
                '노드는 계속 실행되지만 전송은 되지 않습니다.'
            )
            return

        backoff = self._reconnect_min_sec
        while not self._stop.is_set():
            try:
                ws = websocket.create_connection(
                    self._url, timeout=self._connect_timeout_sec
                )
            except Exception as exc:  # noqa: BLE001
                self._node.get_logger().warning(
                    f'[joint_streamer] WebSocket 연결 실패 ({self._log_url}): {exc}; '
                    f'{backoff:.1f}초 후 재시도'
                )
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2.0, self._reconnect_max_sec)
                continue

            with self._lock:
                self._ws = ws
            self._node.get_logger().info(f'[joint_streamer] WebSocket 연결됨: {self._log_url}')
            backoff = self._reconnect_min_sec

            try:
                self._send_loop(ws)
            except Exception as exc:  # noqa: BLE001
                self._node.get_logger().warning(
                    f'[joint_streamer] WebSocket 전송 중 오류: {exc}'
                )
            finally:
                with self._lock:
                    self._ws = None
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass

            if self._stop.is_set():
                break
            self._node.get_logger().warning(
                f'[joint_streamer] WebSocket 연결 끊김; {backoff:.1f}초 후 재연결'
            )
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2.0, self._reconnect_max_sec)

    def _send_loop(self, ws) -> None:
        while not self._stop.is_set():
            if not self._has_pending.wait(timeout=1.0):
                continue
            with self._lock:
                payload = self._pending
                self._pending = None
                self._has_pending.clear()
            if payload is None:
                continue
            ws.send(json.dumps(payload, ensure_ascii=False))


class JointStreamerNode(Node):
    """`/joint_states`를 구독해 joint_1..joint_6 각도를 백엔드 WebSocket으로 스트리밍."""

    def __init__(self) -> None:
        super().__init__('sfarm_joint_streamer_node')
        load_dotenv()

        self.robot_id = str(
            self.declare_parameter('robot_id', os.getenv('ROBOT_ID', 'robot-arm-1')).value
        )
        self.joint_states_topic = str(
            self.declare_parameter(
                'joint_states_topic', os.getenv('JOINT_STATES_TOPIC', '/joint_states')
            ).value
        )
        self.publish_rate_hz = float(
            self.declare_parameter(
                'publish_rate_hz', float(os.getenv('JOINT_STREAM_RATE_HZ', '10.0'))
            ).value
        )
        self.backend_ws_url = str(
            self.declare_parameter(
                'backend_ws_url',
                os.getenv('BACKEND_ROBOT_WS_URL', 'ws://localhost:8000/ws/robot-state'),
            ).value
        )
        self.ws_token = str(
            self.declare_parameter('ws_token', os.getenv('ROBOT_WS_TOKEN', '')).value
        )
        self.joint_names = _parse_name_list(
            self.declare_parameter(
                'joint_names',
                _parse_name_list(os.getenv('JOINT_NAMES', '')) or list(DEFAULT_JOINT_NAMES),
            ).value
        ) or list(DEFAULT_JOINT_NAMES)
        self.joint_name_prefix = str(
            self.declare_parameter(
                'joint_name_prefix', os.getenv('JOINT_NAME_PREFIX', '')
            ).value
        )
        self.joint_name_overrides = _parse_overrides(
            str(
                self.declare_parameter(
                    'joint_name_overrides', os.getenv('JOINT_NAME_OVERRIDES', '')
                ).value
            )
        )
        self.ws_connect_timeout_sec = float(
            self.declare_parameter(
                'ws_connect_timeout_sec',
                float(os.getenv('WS_CONNECT_TIMEOUT_SEC', '5.0')),
            ).value
        )
        self.ws_reconnect_min_sec = float(
            self.declare_parameter(
                'ws_reconnect_min_sec',
                float(os.getenv('WS_RECONNECT_MIN_SEC', '1.0')),
            ).value
        )
        self.ws_reconnect_max_sec = float(
            self.declare_parameter(
                'ws_reconnect_max_sec',
                float(os.getenv('WS_RECONNECT_MAX_SEC', '30.0')),
            ).value
        )

        # ---- RG2 그리퍼(컨트롤박스 DO) 상태 조회 설정
        self.gripper_enabled = bool(
            self.declare_parameter(
                'gripper_enabled',
                os.getenv('GRIPPER_STREAM_ENABLED', 'true').lower() in ('1', 'true', 'yes'),
            ).value
        )
        self.gripper_do_service = str(
            self.declare_parameter(
                'gripper_do_service',
                os.getenv(
                    'GRIPPER_DO_SERVICE',
                    '/dsr01/dsr_controller2/io/get_ctrl_box_digital_output',
                ),
            ).value
        )
        self.gripper_close_do = int(
            self.declare_parameter(
                'gripper_close_do', int(os.getenv('GRIPPER_CLOSE_DO', '1'))
            ).value
        )
        self.gripper_open_do = int(
            self.declare_parameter(
                'gripper_open_do', int(os.getenv('GRIPPER_OPEN_DO', '2'))
            ).value
        )
        self.gripper_open_width_mm = float(
            self.declare_parameter(
                'gripper_open_width_mm', float(os.getenv('GRIPPER_OPEN_WIDTH_MM', '110.0'))
            ).value
        )
        self.gripper_closed_width_mm = float(
            self.declare_parameter(
                'gripper_closed_width_mm',
                float(os.getenv('GRIPPER_CLOSED_WIDTH_MM', '1.0')),
            ).value
        )
        self.gripper_poll_rate_hz = float(
            self.declare_parameter(
                'gripper_poll_rate_hz', float(os.getenv('GRIPPER_POLL_RATE_HZ', '5.0'))
            ).value
        )

        if self.publish_rate_hz <= 0.0:
            self.get_logger().warning(
                f'publish_rate_hz={self.publish_rate_hz} 는 유효하지 않아 10.0으로 대체합니다'
            )
            self.publish_rate_hz = 10.0

        # canonical joint name(joint_1..joint_6) -> 실제 /joint_states 안의 name
        self._source_names: dict[str, str] = self._build_source_names()

        self._latest_lock = threading.Lock()
        self._latest_msg: JointState | None = None
        self._last_values: dict[str, float] = {name: 0.0 for name in self.joint_names}
        self._seq = 0
        self._warned_no_data = False
        self._warned_missing_names = False

        log_url = self.backend_ws_url
        self._sender = WebSocketSender(
            node=self,
            url=self._build_ws_url(),
            log_url=log_url,
            connect_timeout_sec=self.ws_connect_timeout_sec,
            reconnect_min_sec=self.ws_reconnect_min_sec,
            reconnect_max_sec=self.ws_reconnect_max_sec,
        )
        self._sender.start()

        self.subscription = self.create_subscription(
            JointState,
            self.joint_states_topic,
            self._on_joint_states,
            QoSProfile(depth=10),
        )

        period_sec = 1.0 / self.publish_rate_hz
        self.timer = self.create_timer(period_sec, self._on_timer)

        # 그리퍼 상태: DO 인덱스 -> 마지막으로 읽은 값(1=ON, 0=OFF). None이면 아직 모름.
        self._gripper_lock = threading.Lock()
        self._do_values: dict[int, int | None] = {
            self.gripper_close_do: None,
            self.gripper_open_do: None,
        }
        self._do_inflight: set[int] = set()
        self._gripper_client = None
        self._warned_gripper_unavailable = False
        self._setup_gripper_polling()

        self.get_logger().info(
            f'[joint_streamer] "{self.joint_states_topic}" 구독 시작, '
            f'{self.publish_rate_hz}Hz로 {log_url} 에 전송 '
            f'(source names={list(self._source_names.values())})'
        )

    # ---------------------------------------------------------------- gripper
    def _setup_gripper_polling(self) -> None:
        if not self.gripper_enabled:
            self.get_logger().info('[joint_streamer] 그리퍼 상태 스트리밍 비활성화')
            return
        if GetCtrlBoxDigitalOutput is None:
            self.get_logger().warning(
                '[joint_streamer] dsr_msgs2를 import할 수 없어 그리퍼 상태를 보내지 않습니다 '
                '(두산 워크스페이스 setup.bash를 source 했는지 확인)'
            )
            return
        if self.gripper_poll_rate_hz <= 0.0:
            self.gripper_poll_rate_hz = 5.0
        self._gripper_client = self.create_client(
            GetCtrlBoxDigitalOutput, self.gripper_do_service
        )
        self.gripper_timer = self.create_timer(
            1.0 / self.gripper_poll_rate_hz, self._on_gripper_timer
        )
        self.get_logger().info(
            f'[joint_streamer] 그리퍼 DO 조회 시작: {self.gripper_do_service} '
            f'(close=DO{self.gripper_close_do}, open=DO{self.gripper_open_do}, '
            f'{self.gripper_poll_rate_hz}Hz)'
        )

    def _on_gripper_timer(self) -> None:
        client = self._gripper_client
        if client is None:
            return
        if not client.service_is_ready():
            if not self._warned_gripper_unavailable:
                self.get_logger().warning(
                    f'[joint_streamer] 그리퍼 DO 서비스 "{self.gripper_do_service}" 없음; '
                    '그리퍼 상태 없이 조인트만 전송합니다 (gripper_do_service 파라미터 확인)'
                )
                self._warned_gripper_unavailable = True
            with self._gripper_lock:
                for idx in self._do_values:
                    self._do_values[idx] = None
            return
        if self._warned_gripper_unavailable:
            self.get_logger().info('[joint_streamer] 그리퍼 DO 서비스 연결됨')
            self._warned_gripper_unavailable = False

        for idx in self._do_values:
            with self._gripper_lock:
                if idx in self._do_inflight:
                    continue  # 이전 응답이 아직 안 왔으면 요청을 쌓지 않는다
                self._do_inflight.add(idx)
            req = GetCtrlBoxDigitalOutput.Request()
            req.index = idx
            future = client.call_async(req)
            future.add_done_callback(
                lambda fut, index=idx: self._on_do_response(index, fut)
            )

    def _on_do_response(self, index: int, future) -> None:
        value: int | None = None
        try:
            res = future.result()
            if res is not None and res.success:
                # 드라이버는 Drfl->get_digital_output()의 bool을 그대로 넣는다 (1=ON).
                value = 1 if int(res.value) else 0
        except Exception as exc:  # noqa: BLE001
            self.get_logger().debug(f'[joint_streamer] DO{index} 조회 실패: {exc}')
        with self._gripper_lock:
            self._do_inflight.discard(index)
            self._do_values[index] = value

    def _gripper_payload(self) -> dict | None:
        """Convert ctrl-box DO state to RG2 width; None(필드 생략) if undetermined."""
        with self._gripper_lock:
            close_on = self._do_values.get(self.gripper_close_do)
            open_on = self._do_values.get(self.gripper_open_do)
        if close_on is None or open_on is None:
            return None
        if close_on and not open_on:
            return {
                'type': GRIPPER_TYPE,
                'width_mm': self.gripper_closed_width_mm,
                'is_gripping': True,
            }
        if open_on and not close_on:
            return {
                'type': GRIPPER_TYPE,
                'width_mm': self.gripper_open_width_mm,
                'is_gripping': False,
            }
        return None  # 둘 다 ON/OFF인 과도 상태 -> 마지막 폭 유지

    def _build_source_names(self) -> dict[str, str]:
        """canonical joint 이름 -> /joint_states 안에서 실제로 찾을 이름 매핑을 만든다.

        우선순위: joint_name_overrides(명시적 매핑) > joint_name_prefix(접두어) > 그대로.
        """
        source_names: dict[str, str] = {}
        for name in self.joint_names:
            if name in self.joint_name_overrides:
                source_names[name] = self.joint_name_overrides[name]
            else:
                source_names[name] = f'{self.joint_name_prefix}{name}'
        return source_names

    def _build_ws_url(self) -> str:
        if not self.ws_token:
            return self.backend_ws_url
        separator = '&' if '?' in self.backend_ws_url else '?'
        return f'{self.backend_ws_url}{separator}token={quote(self.ws_token, safe="")}'

    def _on_joint_states(self, msg: JointState) -> None:
        with self._latest_lock:
            self._latest_msg = msg

    def _on_timer(self) -> None:
        with self._latest_lock:
            msg = self._latest_msg

        if msg is None:
            if not self._warned_no_data:
                self.get_logger().warning(
                    f'[joint_streamer] 아직 "{self.joint_states_topic}"에서 메시지를 '
                    '받지 못했습니다; 전송을 건너뜁니다 (두산 드라이버가 떠 있는지 확인)'
                )
                self._warned_no_data = True
            return
        self._warned_no_data = False

        name_to_index = {name: i for i, name in enumerate(msg.name)}
        found_any = False
        for canonical, source_name in self._source_names.items():
            idx = name_to_index.get(source_name)
            if idx is not None and idx < len(msg.position):
                self._last_values[canonical] = float(msg.position[idx])
                found_any = True

        if not found_any:
            if not self._warned_missing_names:
                self.get_logger().warning(
                    '[joint_streamer] "{}"에서 기대한 조인트 이름을 찾지 못했습니다 '
                    '(기대: {}, 실제: {}). joint_name_prefix / joint_name_overrides '
                    '파라미터를 확인하세요.'.format(
                        self.joint_states_topic,
                        list(self._source_names.values()),
                        list(msg.name),
                    )
                )
                self._warned_missing_names = True
            return
        self._warned_missing_names = False

        self._seq += 1
        header_stamp_ms = (
            msg.header.stamp.sec * 1000 + msg.header.stamp.nanosec // 1_000_000
        )
        timestamp_ms = header_stamp_ms if header_stamp_ms > 0 else int(time.time() * 1000)

        payload = {
            'robot_id': self.robot_id,
            'seq': self._seq,
            'timestamp_ms': timestamp_ms,
            'angle_unit': ANGLE_UNIT,
            'joints': dict(self._last_values),
            'source': PAYLOAD_SOURCE,
        }
        gripper = self._gripper_payload()
        if gripper is not None:
            payload['gripper'] = gripper
        self._sender.enqueue_latest(payload)

    def destroy_node(self) -> None:
        self._sender.stop()
        super().destroy_node()


def main(args=None) -> None:
    """Entry point for sfarm_joint_streamer node."""
    rclpy.init(args=args)
    node = JointStreamerNode()
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
