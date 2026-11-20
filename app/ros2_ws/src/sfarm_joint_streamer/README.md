# `sfarm_joint_streamer` 실행 가이드

로봇 팔(두산 M0609)의 실시간 조인트 각도를 `/joint_states`(`sensor_msgs/msg/JointState`)에서
**구독만** 하고, 백엔드 WebSocket 엔드포인트(`/ws/robot-state`)로 스로틀링해 전송하는 패키지입니다.
티칭팬던트 페이지의 3D 로봇팔 뷰어가 이 프레임을 받아 실제 로봇 자세를 실시간으로 반영합니다.

**`sfarm_bridge` / `sfarm_robot` / `sfarm_interfaces`는 전혀 건드리지 않습니다** — 그 패키지들이
publish하는 토픽(`/joint_states`, 두산 드라이버 표준 토픽)을 구독만 합니다.

---

## 1. 사전 준비

### 1.1 `websocket-client` 설치

이 노드는 `websocket-client`(pip, import name: `websocket`)를 사용합니다. `package.xml`에
rosdep 키(`python3-websocket-client`)를 등록해 두었지만, 이 환경에서 해석되지 않으면 직접
설치하세요:

```bash
pip install websocket-client
```

설치되어 있지 않아도 노드 자체는 죽지 않고, 전송만 비활성화된 채로 에러 로그를 남깁니다.

### 1.2 `.env` (선택)

필요하면 `app/ros2_ws/src/sfarm_joint_streamer/.env`에 아래 값을 채워 넣을 수 있습니다
(ROS 파라미터로 직접 넘겨도 동일하게 동작합니다):

```dotenv
ROBOT_ID=robot-arm-1
JOINT_STATES_TOPIC=/joint_states
JOINT_STREAM_RATE_HZ=10.0
BACKEND_ROBOT_WS_URL=ws://localhost:8000/ws/robot-state
ROBOT_WS_TOKEN=<TOKEN>
JOINT_NAME_PREFIX=
JOINT_NAME_OVERRIDES=
```

---

## 2. 빌드 및 환경 로드

> **주의**: 반드시 `app/ros2_ws` **루트**에서 빌드하세요 (`src/` 내부에서 `colcon build` 실행 금지).

```bash
source /opt/ros/jazzy/setup.bash
cd app/ros2_ws

colcon build --symlink-install --packages-select sfarm_joint_streamer
source install/setup.bash
```

---

## 3. 노드 실행

```bash
# 기본 실행 (.env 또는 기본값 사용)
ros2 run sfarm_joint_streamer joint_streamer

# ROS 파라미터로 직접 지정
ros2 run sfarm_joint_streamer joint_streamer --ros-args \
  -p backend_ws_url:=ws://localhost:8000/ws/robot-state \
  -p ws_token:=<TOKEN> \
  -p publish_rate_hz:=10.0

# launch 파일로 실행 (동일한 오버라이드 가능)
ros2 launch sfarm_joint_streamer joint_streamer.launch.py \
  backend_ws_url:=ws://localhost:8000/ws/robot-state \
  ws_token:=<TOKEN>
```

조인트 이름이 `joint_1..joint_6`이 아니라 prefix가 붙어 있다면(예: `dsr01_joint_1`):

```bash
ros2 run sfarm_joint_streamer joint_streamer --ros-args -p joint_name_prefix:=dsr01_
```

완전히 다른 이름이라면 `joint_name_overrides`로 개별 매핑:

```bash
ros2 run sfarm_joint_streamer joint_streamer --ros-args \
  -p joint_name_overrides:="joint_1=j1,joint_2=j2,joint_3=j3,joint_4=j4,joint_5=j5,joint_6=j6"
```

---

## 4. 통신 규격

### 4.1 구독 (입력)

| 토픽 | 타입 | 발행 주체 |
| :--- | :--- | :--- |
| `/joint_states` (파라미터 `joint_states_topic`로 변경 가능) | `sensor_msgs/msg/JointState` | 두산 로봇 드라이버 |

### 4.2 WebSocket 전송 (출력, 백엔드/프론트엔드와 확정된 규격)

연결: `backend_ws_url` + (`ws_token`이 있으면) `?token=<TOKEN>` 쿼리 파라미터.

전송 payload (메시지당 1개, 래핑 없음):

```json
{
  "robot_id": "robot-arm-1",
  "seq": 123,
  "timestamp_ms": 1700000000000,
  "angle_unit": "rad",
  "joints": {"joint_1": 0.0, "joint_2": 0.0, "joint_3": 1.57, "joint_4": 0.0, "joint_5": 1.57, "joint_6": 0.0},
  "source": "ros2_sfarm_bridge"
}
```

- `seq`: 전송마다 1 증가하는 정수.
- `timestamp_ms`: `/joint_states` 헤더 타임스탬프가 있으면 그 값, 없으면 전송 시점.
- `joints`에 매핑되는 조인트를 하나도 찾지 못하면 해당 프레임은 보내지 않습니다
  (이름 매핑이 잘못됐다는 경고 로그가 1회 출력됩니다).

---

## 5. 자주 겪는 문제

- **`"websocket-client" 패키지가 설치되어 있지 않아...` 로그**: `pip install websocket-client`.
- **`기대한 조인트 이름을 찾지 못했습니다` 경고**: `/joint_states`의 실제 `name[]` 값을
  `ros2 topic echo /joint_states --once`로 확인한 뒤 `joint_name_prefix` 또는
  `joint_name_overrides`를 조정하세요.
- **`아직 ".../joint_states"에서 메시지를 받지 못했습니다` 경고**: 두산 드라이버(또는
  joint_state_publisher)가 실행 중인지, `ROS_DOMAIN_ID`가 양쪽에서 같은지(기본 `20`) 확인하세요.
- **WebSocket이 계속 재연결 로그만 찍을 때**: 백엔드 `/ws/robot-state` 엔드포인트가 떠 있는지,
  `ws_token`이 백엔드가 기대하는 값과 일치하는지 확인하세요. 노드는 재연결에 실패해도 죽지
  않고 지수 백오프(`ws_reconnect_min_sec`~`ws_reconnect_max_sec`)로 계속 재시도합니다.

---

## 그리퍼(RG2) 상태 스트리밍

RG2는 `/joint_states`에 조인트가 없고 컨트롤박스 디지털 출력(DO1=닫기, DO2=열기)으로 제어되므로,
노드가 두산 드라이버 서비스 `/dsr01/dsr_controller2/io/get_ctrl_box_digital_output`을 5Hz로 조회해
payload에 `gripper: {type: "rg2", width_mm, is_gripping}`를 실어 보냅니다(열림 110mm / 닫힘 1mm = 보드 두께).
홈 화면 3D 뷰어는 이 값으로 그리퍼를 열고 닫습니다.

- 두산 워크스페이스(`dsr_msgs2`)를 source 한 셸에서 실행해야 합니다. 없으면 그리퍼 필드만 생략됩니다.
- 서비스가 없거나 DO 상태가 모호하면(둘 다 ON/OFF) 필드를 생략 → 뷰어는 마지막 폭을 유지합니다.
- 파라미터: `gripper_enabled`, `gripper_do_service`, `gripper_close_do`, `gripper_open_do`,
  `gripper_open_width_mm`, `gripper_closed_width_mm`, `gripper_poll_rate_hz`
