# PRD — 웹 티칭 팬던트(실물 로봇 조그 제어)

작성일: 2026-11-17 · 작성자: 류병옥 (Claude 보조 작성) · 개정: 2026-11-18

> **2026-11-18 개정:** 가상 로봇(`virtual-robot`, `/ws/bridge`, `DispatcherService`, `RobotState`)이 코드에서 제거됐다. 이 문서에서 가상 로봇을 "무관한 별도 경로"로 언급하던 부분을 정리했고, 웹의 조그 버튼이 가상 로봇 연결 상태(`bridge_connected`)에 묶여 실물 로봇만 쓸 때 항상 잠기던 문제를 고친 내용을 반영했다 (8장). 상호 배제가 UNLOAD 단계를 막지 못하는 문제를 새로 발견해 3장·10장에 적었다.

관련 문서: `assets/docs/prd.md`(기존 전체 PRD), `assets/docs/prd-work-request-sqs.md`(SQS 작업요청 — `robot-commands`/`robot-events` 스키마와 프로듀서 패턴의 기준), `app/ros2_ws/src/sfarm_bridge`·`sfarm_robot`(ROS 2 담당자 작업물)

## 1. 배경과 목적

작업요청(LOAD/UNLOAD) 기능은 `robot-commands` SQS를 통해 실물 로봇에 **미리 정해진** 동작(적재대 집기, 프린터 배치, 수령)만 지시한다. 로봇의 실제 이동 좌표(`app/ros2_ws/src/sfarm_robot/sfarm_robot/poses.py`의 `posj`/`posx` 값)를 확인하거나 조정하려면 현재는 두산 로봇 자체의 물리적 티칭 펜던트나 DRL 프로그램을 직접 써야 한다.

이 PRD는 운영자가 **웹 대시보드에서 방향키 모양의 버튼을 클릭해 실물 로봇 팔을 한 스텝씩 조금씩 움직여볼 수 있는 간단한 조그(jog) 패널**을 정의한다. 기준 좌표계(Base/Tool)를 고르고, Cartesian(X/Y/Z/Rx/Ry/Rz) 또는 Joint(J1~J6) 모드로 방향키를 눌러 로봇을 이동시킨다.

### 목표

- 운영자가 웹에서 기준 좌표계와 조그 모드(Cartesian/Joint)를 선택하고, 방향키 버튼을 클릭해 실물 로봇을 한 스텝씩 움직일 수 있다.
- 운영자가 같은 패널에서 그리퍼(OnRobot RG2)를 열기/닫기할 수 있다 (단순 개폐만 — 파지 상태 피드백은 범위 밖, 아래 참고).
- 조그·그리퍼 명령은 기존 `robot-commands`/`robot-events` SQS 왕복 계약과 같은 체계(스키마 확장)로 ROS 2 쪽에 전달된다 — ROS 2 쪽 코드는 이 PRD가 정의한 신규 메시지 타입만 소비하도록 구현하면 된다.
- 실물 로봇을 다루는 기능이므로, 평소 작업요청 디스패치(LOAD/UNLOAD)와 조그·그리퍼 조작이 동시에 로봇을 움직이는 상황을 막는다.

### 범위

- 웹: "티칭 팬던트" 패널 — 활성화 스위치(안전 확인 모달 포함), 기준 좌표계 선택(Base/Tool), 모드 전환(Cartesian/Joint), 스텝 크기 선택, 방향키 버튼(축당 +/- 2개), 그리퍼 열기/닫기 버튼, 현재 위치/로봇 상태 표시, 정지 버튼.
- 서버: 조그 1스텝·그리퍼 개폐 요청 API → 작업요청(실물 로봇) 경로와의 상호 배제 확인(3장) → `robot-commands`에 JOG/GRIPPER 명령 produce → `robot-events`의 완료/실패 이벤트 소비 → 현재 위치·상태·그리퍼 상태 갱신 → 웹 브로드캐스트.
- SQS 인터페이스: `robot-commands`에 신규 메시지 타입 `JOG`·`GRIPPER`, `robot-events`에 신규 이벤트 타입 `jog_complete`/`jog_failed`·`gripper_complete`/`gripper_failed` 스키마 정의(7장).

### 범위 밖 (이 PRD에서 다루지 않음)

- **연속 누름(press-and-hold) 조그.** SQS 큐 왕복(FIFO 발행 → ROS 2 소비 → 실행 → 이벤트 응답)은 왕복 지연이 있어 "누르고 있는 동안 계속 움직이는" 실시간 제어에는 부적합하다. 이번 PRD는 **클릭 1회 = 스텝 1회 이동**(discrete step jog)만 다룬다. 연속 조그가 꼭 필요하면 SQS가 아닌 별도의 낮은 지연 채널(예: ROS 2 쪽과 WebSocket 직결)이 필요하며, 이는 후속 과제로 남긴다.
- **가상 로봇 지원.** 실물 로봇 전용이다 (가상 로봇은 2026-11-18 제거됨).
- **티칭 포인트 저장/재사용.** 조그로 이동한 위치를 이름 붙여 저장했다가 LOAD/UNLOAD 동작(`poses.py`)에 반영하는 기능은 다루지 않는다 — 이번 기능은 단순 조그 확인/조정 용도이고, 좌표를 실제 동작에 반영하는 것은 여전히 ROS 2 쪽에서 `poses.py`를 직접 수정하는 별도 작업이다.
- **그리퍼 파지 상태/힘 센서 피드백.** 그리퍼는 열기/닫기 명령만 보낸다 — 기존 `grip_and_check`처럼 `get_tool_force`로 파지 성공 여부를 판정해 화면에 보여주는 것은 다루지 않는다. 명령이 로봇에 전달되어 실행됐는지(성공/실패)만 확인한다.
- **ROS 2 쪽 실제 조그 실행 구현** (`DSR_ROBOT2` API 호출, 안전 정지 로직 등). 이 PRD는 7장의 SQS 메시지 스키마까지만 정의한다. 실제 모션 명령 구현은 ROS 2 담당자 영역이다.
- 로그인/권한 관리, 복수 운영자 동시 제어(2장에서 단일 소유자 가정만 둔다).
- 하드웨어 수준 안전장치(비상정지 버튼, 협동로봇 속도 제한 모드 등) — 9장에서 소프트웨어 상의 안전장치만 다룬다.

### 용어

| 용어 | 뜻 |
| --- | --- |
| 조그(jog) | 로봇을 한 번에 조금씩(스텝 단위) 수동으로 이동시키는 동작 |
| 기준 좌표계 | 조그 방향이 어느 좌표계를 기준으로 해석되는지. Base(로봇 베이스 고정 좌표계) 또는 Tool(툴 끝단 기준 좌표계) |
| Cartesian 모드 | X/Y/Z(mm 이동) + Rx/Ry/Rz(deg 회전) 6축 조그 |
| Joint 모드 | J1~J6 관절 각도(deg)를 축별로 개별 조그 |
| 스텝 크기 | 버튼 1회 클릭당 이동하는 거리(mm) 또는 각도(deg) |
| 조그 세션 | 티칭 팬던트가 활성화된 상태. 세션 동안 새 작업요청의 load 발행은 보류된다 (3장) |
| 그리퍼 열기/닫기 | OnRobot RG2 그리퍼 개폐. 기존 `motions.py`의 `grip_open()`/`grip_close()`(디지털 출력 채널 1/2)와 같은 동작을 단순 버튼으로 호출 |

## 2. 사용자 흐름 (웹)

1. 운영자가 대시보드에서 **"티칭 팬던트"** 패널(또는 별도 페이지)을 연다.
2. **활성화** 스위치를 켠다 → 확인 모달("실물 로봇이 움직입니다. 주변에 사람이나 장애물이 없는지 확인하세요") → 확인 시 서버에 활성화 요청.
   - 서버가 진행 중인 `robot_tasks`(LOAD)가 없는 경우에만 활성화를 허용한다(3장 A). 그렇지 않으면 활성화 실패 + 이유 표시("작업 진행 중이라 조그를 쓸 수 없습니다").
   - 활성화 성공 시 이 조그 세션이 끝날 때까지 새 작업요청은 load를 보내지 않고 WAITING으로 남는다 (3장 B).
3. **기준 좌표계**(Base/Tool), **모드**(Cartesian/Joint), **스텝 크기**를 고른다.
4. 방향키 모양 버튼(예: Cartesian 모드면 X+/X-/Y+/Y-/Z+/Z-/Rx+/Rx-/Ry+/Ry-/Rz+/Rz- 12개, Joint 모드면 J1+/J1-…J6+/J6- 12개)을 클릭한다.
   - 클릭 즉시 해당 버튼(들)이 비활성화(또는 로딩 표시)되고, 서버가 이전 스텝의 완료 응답을 받기 전까지는 다음 클릭을 받지 않는다(8.2 "스텝 상호 배제" 참고) — 클릭을 빠르게 여러 번 눌러도 로봇에는 한 번에 한 스텝만 전달된다.
   - 서버 응답(완료/실패)에 따라 현재 위치 표시가 갱신되고 버튼이 다시 활성화된다.
5. **그리퍼 열기/닫기** 버튼을 클릭하면 방향키와 같은 방식(이전 명령 완료 전 재클릭 무시)으로 그리퍼 개폐 명령이 전달된다. 완료/실패 응답에 따라 그리퍼 상태 표시(열림/닫힘/실패)가 갱신된다.
6. 운영자가 **비활성화** 스위치를 끄거나 패널을 떠나면 조그 세션이 끝난다. 세션 중 WAITING으로 남은 작업요청은 자동으로 재발행되지 않는다 (10장).
7. **정지** 버튼은 진행 중인 스텝(조그 또는 그리퍼)에 대해 취소/정지를 요청한다 (8.4 참고 — SQS 특성상 "이미 발행된 명령"을 취소하는 데는 한계가 있음을 사용자에게 알려야 한다).

## 3. 작업요청(실물 로봇) 경로와의 상호 배제

로봇은 작업요청 경로(`WorkRequestService` → `robot-commands` SQS)로만 움직이며, 이 경로에는 "로봇이 쉬고 있는가"를 보는 루프가 없다 — 요청이 오면 그 자리에서 명령을 발행한다. 그래서 조그 세션과 작업요청이 서로를 막는 체크를 양쪽에 둔다.

상호 배제는 아래 두 방향으로 구현돼 있다.

```
(A) 조그 세션 활성화 요청
  └─ robot_tasks 중 "실물 로봇 경로"(start_pos_id IS NOT NULL) 이면서
     status가 DISPATCHED/RUNNING인 행이 있는지 확인 (신규 리포지토리 메서드)
       └─ 있으면: 활성화 거부 ("작업 진행 중이라 조그를 쓸 수 없습니다")
       └─ 없으면: 조그 세션 시작 (서버 런타임 상태 플래그 ON)

(B) WorkRequestService.create() (작업요청 생성 시)
  └─ 조그 세션이 활성 상태인지 확인 (신규: TeachingPendantService의 세션 상태 조회)
       └─ 활성 상태면: 기존 "빈 프린터 없음"과 같은 방식으로 처리 —
          주문은 WAITING으로 남기고 LOAD를 SQS로 보내지 않음, 201 응답(대기 등록)
       └─ 비활성 상태면: 기존 로직대로 진행
```

**구현:** (A)는 `RobotTaskRepository.get_active_real_robot_task_locked`(`status IN (DISPATCHED, RUNNING) AND start_pos_id IS NOT NULL`), (B)는 `WorkRequestService.create()`의 베드 확인보다 앞에 둔 `TeachingPendantService.is_session_active()` 체크다.

**알려진 빈틈 — UNLOAD 단계 (2026-11-18 발견, 미해결):** `robot_tasks`에는 LOAD만 기록되고 unload1/unload2는 기록되지 않는다. 그래서
- (A) 로봇이 unload1/unload2를 수행 중이어도 조그 세션 활성화가 허용된다.
- (B) 조그 세션 중에도 출력 타이머가 끝나면 unload1이, 수령하기·success_unload1 이후에는 unload2가, success_load1 이후에는 load2가 그대로 발행된다. (B) 체크는 작업요청(load) 시점에만 있다.

실물 로봇이 조그 중에 다른 명령을 받을 수 있으므로 안전상 막아야 한다. 해결 방향은 10장 참고.

참고로 이 두 체크는 **완전한 레이스 방지를 보장하지 않는다** — (A)와 (B) 사이, 또는 (B)의 확인과 실제 SQS produce 사이에 시간차가 있다. 엄밀한 동시성 보호가 필요하면 기존 `SELECT ... FOR UPDATE` 패턴(작업요청 PRD 9장)과 같은 잠금을 조그 세션 상태에도 적용해야 하는데, 세션 상태를 DB가 아니라 런타임 메모리에 두기로 했으므로(5장) 이 레이스는 낮은 빈도의 엣지 케이스로 남겨두고 10장 미결 사항에 적어둔다.

## 4. 기능 요구사항

| ID | 기능 | 상세 | 우선순위 |
| --- | --- | --- | --- |
| TP-01 | 활성화/비활성화 | 안전 확인 모달 → 활성화 요청. 실물 로봇 경로(작업요청) 활성 작업 없음 확인 후에만 허용(3장 A) | P0 |
| TP-02 | 작업요청 경로 상호 배제 | 조그 세션 중 `WorkRequestService.create()`가 새 LOAD를 SQS로 보내지 않고 주문을 WAITING으로 남김(3장 B) | P0 |
| TP-03 | 기준 좌표계 선택 | Base/Tool 토글 | P0 |
| TP-04 | 모드 전환 | Cartesian ↔ Joint 토글 | P0 |
| TP-05 | 스텝 크기 선택 | Cartesian: 선형(mm)/회전(deg) 프리셋, Joint: deg 프리셋. 최대값 상한 적용(9장) | P0 |
| TP-06 | 방향키 조그 | 버튼 클릭 1회 = 1스텝. 이전 스텝 완료 전 재클릭 무시(8.2) | P0 |
| TP-07 | 현재 위치 표시 | 완료 이벤트 수신 시 posx/posj 값 갱신 표시 | P0 |
| TP-08 | 상태 표시 | 서버 연결 상태(/ws/client) 및 조그 세션 활성·소유 여부 표시. 로봇과는 SQS로만 통신하므로 별도 "로봇 연결" 상태는 없다 | P0 |
| TP-09 | 정지 요청 | 진행 중 스텝에 정지 요청(한계는 8.4에 명시해 사용자에게 고지) | P1 |
| TP-10 | 조그 실패 처리 | `jog_failed` 수신 시 에러 표시, 버튼 재활성화, 세션 유지 | P0 |
| TP-11 | 세션 타임아웃 | 일정 시간(예: 10초) 내 완료/실패 응답 없으면 타임아웃 에러 + 운영자 확인 요구 | P1 |
| TP-12 | 그리퍼 열기/닫기 | 버튼 클릭 1회 = 개폐 명령 1회. 이전 명령 완료 전 재클릭 무시(조그와 같은 상호 배제 규칙) | P0 |
| TP-13 | 그리퍼 상태 표시 | 완료 이벤트 수신 시 열림/닫힘 상태 표시 (파지 성공 여부 판정은 범위 밖, 1장 참고) | P0 |

## 5. 데이터 모델 변경

### 신규 테이블/컬럼 없음 (제안)

조그 명령은 `orders`/`robot_tasks`처럼 "주문"에 묶이는 작업이 아니므로, 기존 `robot_tasks`(`order_id` FK 필수)에 끼워 넣지 않는다. 대신:

- **조그 세션 상태**는 DB에 영속화하지 않고 서버 런타임 상태(기존 `app/core` 런타임 상태와 같은 자리)로만 관리한다 — 서버 재시작 시 세션은 자동 종료(비활성화)된다. 로봇의 중간 상태가 애매해지는 것을 막기 위해, 재시작 후 조그 세션은 복원하지 않고 항상 비활성 상태로 시작한다.
- **추적성**은 기존 `event_logs`로 충분하다 — 조그 명령 발행/완료/실패를 `event_logs`에 기존 작업요청과 같은 방식으로 남긴다 (9장 비기능요구사항).

이 결정("새 테이블 없이 런타임 상태 + event_logs만으로 충분한가")은 10장 미결 사항으로 남긴다 — 조그 이력을 나중에 조회할 필요가 생기면 신규 테이블이 필요해질 수 있다.

### 조그 세션 플래그와 신규 리포지토리 메서드

조그 세션은 런타임 플래그(활성 여부 + 소유자, `app/core/runtime.py`의 `TeachingPendantSession`)로만 관리하고, 3장 (A)는 `RobotTaskRepository.get_active_real_robot_task_locked`로 진행 중 작업을 확인한다.

## 6. API 명세

### POST /api/teaching-pendant/session (활성화/비활성화)

| 항목 | 내용 |
| --- | --- |
| 요청 | `{ "enable": true }` 또는 `{ "enable": false }` |
| 응답 200 (활성화 성공) | `{ "enabled": true, "current_pose": { "space": "TASK", "posx": [...] } }` |
| 응답 4xx (활성화 거부) | `{ "error_code": "ROBOT_BUSY", "message": "작업 진행 중이라 조그를 쓸 수 없습니다" }` |

### POST /api/teaching-pendant/jog (방향키 1회 클릭)

| 항목 | 내용 |
| --- | --- |
| 요청 | `{ "space": "TASK", "ref_frame": "BASE", "axis": "X", "direction": 1, "step_size": 5 }` (Joint 모드면 `"space": "JOINT", "axis": "J1".."J6"`, `ref_frame` 없음) |
| 응답 202 | `{ "jog_id": "uuid" }` — 비동기 처리, 완료/실패는 웹소켓 이벤트(6.3 유사)로 통지 |
| 응답 409 | 이전 스텝이 아직 진행 중이거나 세션이 비활성 상태 |

### POST /api/teaching-pendant/gripper (그리퍼 열기/닫기)

| 항목 | 내용 |
| --- | --- |
| 요청 | `{ "action": "OPEN" }` 또는 `{ "action": "CLOSE" }` |
| 응답 202 | `{ "gripper_cmd_id": "uuid" }` — 비동기 처리, 완료/실패는 웹소켓 이벤트로 통지 |
| 응답 409 | 이전 조그/그리퍼 명령이 아직 진행 중이거나 세션이 비활성 상태 |

### POST /api/teaching-pendant/stop

| 항목 | 내용 |
| --- | --- |
| 요청 | 바디 없음 |
| 응답 | 정지 요청 접수(8.4의 한계 고지) |

### 웹소켓 이벤트 (기존 `/ws/client` 봉투 재사용)

| type | data | 발생 시점 |
| --- | --- | --- |
| teaching_pendant.session_changed | enabled, owner | 활성화/비활성화 시 |
| teaching_pendant.jog_completed | jog_id, current_pose | `jog_complete` 이벤트 수신 시 |
| teaching_pendant.jog_failed | jog_id, error_code | `jog_failed` 이벤트 수신 또는 타임아웃 시 |
| teaching_pendant.gripper_completed | gripper_cmd_id, state (`OPEN`\|`CLOSE`) | `gripper_complete` 이벤트 수신 시 |
| teaching_pendant.gripper_failed | gripper_cmd_id, error_code | `gripper_failed` 이벤트 수신 또는 타임아웃 시 |

## 7. SQS 인터페이스 명세 (robot-commands / robot-events 확장)

기존 `robot-commands.fifo`(`assets/docs/prd-work-request-sqs.md` 7장)에 신규 메시지 타입을 추가한다. LOAD/UNLOAD와 그룹을 분리해, 조그 명령이 LOAD/UNLOAD 대기열에 걸려 늦게 처리되는 일이 없도록 한다 (단, 3장의 상호 배제 전제상 조그 세션 중에는 LOAD/UNLOAD가 아예 발행되지 않아야 하므로, 정상 상황에서는 그룹 경합이 생기지 않는 것이 설계 의도다).

| 필드 | 값 |
| --- | --- |
| 큐 | `robot-commands.fifo` (기존 큐 재사용) |
| MessageGroupId | 고정값 `"jog"` (LOAD의 `"load"` 그룹과 분리) |
| MessageDeduplicationId | `"jog-{jog_id}"` |
| body.type | `"JOG"` |
| body.jog_id | 조그 요청 UUID |
| body.space | `"TASK"` 또는 `"JOINT"` |
| body.ref_frame | `"BASE"` 또는 `"TOOL"` (space=TASK일 때만) |
| body.axis | TASK: `"X"\|"Y"\|"Z"\|"RX"\|"RY"\|"RZ"`, JOINT: `"J1".."J6"` |
| body.direction | `1` 또는 `-1` |
| body.step_size | TASK 선형: mm, TASK 회전/JOINT: deg |

```json
{
  "type": "JOG",
  "jog_id": "a1b2c3",
  "space": "TASK",
  "ref_frame": "BASE",
  "axis": "X",
  "direction": 1,
  "step_size": 5
}
```

`robot-events`에는 완료/실패 이벤트를 추가한다.

```json
{ "jog_id": "a1b2c3", "status": "jog_complete", "posx": [x, y, z, a, b, c] }
```

```json
{ "jog_id": "a1b2c3", "status": "jog_failed", "error_code": "NOT_REACHABLE" }
```

### 그리퍼 명령 (robot-commands / robot-events 확장)

조그와 같은 그룹(`MessageGroupId="jog"`)에 넣는다 — 조그와 그리퍼 모두 같은 조그 세션 안에서 순서대로 한 번에 하나씩만 실행되면 되므로, 그룹을 나눌 이유가 없다.

| 필드 | 값 |
| --- | --- |
| 큐 | `robot-commands.fifo` (기존 큐 재사용) |
| MessageGroupId | `"jog"` (조그 명령과 공유) |
| MessageDeduplicationId | `"grip-{gripper_cmd_id}"` |
| body.type | `"GRIPPER"` |
| body.gripper_cmd_id | 그리퍼 명령 UUID |
| body.action | `"OPEN"` 또는 `"CLOSE"` |

```json
{ "type": "GRIPPER", "gripper_cmd_id": "d4e5f6", "action": "CLOSE" }
```

```json
{ "gripper_cmd_id": "d4e5f6", "status": "gripper_complete", "state": "CLOSE" }
```

```json
{ "gripper_cmd_id": "d4e5f6", "status": "gripper_failed", "error_code": "TIMEOUT" }
```

ROS 2 쪽 실행은 기존 `motions.py`의 `grip_open()`/`grip_close()`(디지털 출력 채널 1/2, `wait(1.5)`)를 그대로 호출하는 정도로 충분할 것으로 예상한다 — 파지 성공 여부 판정(`get_tool_force`)은 1장에서 범위 밖으로 뺐으므로, `gripper_complete`는 "명령을 실행했다"는 의미이고 "제대로 잡았다"는 의미가 아니다.

**확인 필요 (ROS 2 담당자):** 실제 조그 실행은 `DSR_ROBOT2`의 어떤 API로 할지(예: `movej`/`movel`을 상대 이동으로 호출하는 방식인지, 별도 jog 전용 API가 있는지), 그리고 `posx`의 ZYZ 오일러각 표현을 응답에 그대로 쓸지는 ROS 2 쪽 구현에 달려 있다 — 이 표는 "서버가 보내고 받아야 하는 정보"를 정의한 것이고, 실제 구현 시 ROS 2 담당자와 필드를 대조해야 한다 (기존 work-request PRD 7장과 같은 패턴).

## 8. 예외 처리

| 상황 | 처리 |
| --- | --- |
| 활성화 요청 시 작업 진행 중 | 활성화 거부, 이유 표시 (UNLOAD 진행 중은 감지 못함 — 3장 빈틈) |
| 8.2 스텝 상호 배제 | 이전 `jog_id`의 완료/실패 응답 전 새 조그 요청은 서버가 409로 거부. 버튼도 프론트에서 비활성화해 이중 방지 |
| 세션 타임아웃(TP-11) | 완료/실패 응답이 일정 시간 내 오지 않으면 타임아웃 에러 표시, 운영자가 로봇 상태를 직접 확인하도록 안내. 세션은 자동으로 비활성화하지 않고 운영자 판단에 맡김(로봇이 실제로 움직이고 있을 수 있으므로 섣불리 "비활성화"로 되돌리지 않는다) |
| 8.4 정지 요청의 한계 | SQS는 이미 큐에 들어가거나 ROS 2가 수신한 명령을 "취소"하는 기본 수단이 없다. `POST /stop`은 **다음 스텝을 보내지 않도록 막는 것**과 ROS 2 쪽에 정지 신호를 전달하는 것까지만 보장하며, 이미 실행 중인 스텝 자체를 중간에 멈추는 것은 ROS 2 쪽 구현(모션 중단 가능 여부)에 달려 있다. 이 한계를 UI에 "정지 요청 중 — 이미 시작된 이동은 완료될 수 있음"처럼 명시해야 한다 |
| 조그 중 서버 연결 끊김(/ws/client) | 모든 방향키·그리퍼 버튼 비활성화 (세션 자체는 서버에 유지). 로봇 쪽 무응답은 TP-11 타임아웃으로 드러난다. 이전에는 버튼이 가상 로봇 연결(`bridge_connected`)에도 묶여 있어 실물 로봇만 쓸 때 항상 잠겨 있었다 — 2026-11-18 수정 |
| 그리퍼 명령 실패 | `gripper_failed` 수신 시 에러 표시, 버튼 재활성화, 세션 유지 (조그 실패 처리와 동일, TP-10 참고) |
| 알 수 없는 jog_id/gripper_cmd_id 이벤트(중복 수신 등) | 무시 (기존 PRD 9.5 원칙과 동일) |

## 9. 비기능 요구사항 (안전 포함)

| 항목 | 기준 |
| --- | --- |
| 스텝 크기 상한 | Cartesian 선형 ≤ 20mm, 회전 ≤ 15deg, Joint ≤ 15deg (과도한 1스텝 이동 방지). 상한값은 ROS 2 담당자와 실측 후 조정 가능 |
| 속도/가속도 | 조그 전용으로 낮은 기본값 사용 (기존 `motions.py` 기본값 `VELJ=ACCJ=30`, `VELX=ACCX=100`보다 더 낮게 — 예: 그 절반 이하) — 실제 값은 ROS 2 담당자 확인 필요 |
| 상호 배제 | 조그 세션 중 LOAD/UNLOAD 발행 금지, 반대로 LOAD/UNLOAD 진행 중 조그 세션 활성화 금지 (현재 UNLOAD 단계와 load2는 미보장 — 3장 빈틈) |
| 응답 시간 | 스텝 요청 → 완료 이벤트까지 일반적으로 수 초 내 (SQS 왕복 + 실제 이동 시간). 이 지연 때문에 연속 조그는 지원하지 않는다(1장 범위 밖) |
| 추적성 | 모든 JOG 명령·완료·실패를 `event_logs`에 기록 (work_id 대신 jog_id 사용) |
| 기본 안전 상태 | 페이지 새로고침·재접속 시 조그 세션은 항상 비활성 상태로 시작 (복원하지 않음) |

## 10. 미결 사항

- [ ] **UNLOAD 단계 상호 배제 (안전, 우선 처리 필요)** — 3장 "알려진 빈틈". 해결 방향 후보: (1) 세션 활성 중에는 load2/unload1/unload2 발행을 보류하고 세션 종료 시 이어서 발행, (2) 세션 활성화 조건에 "UNLOADING 주문 또는 PRINT_DONE 후 unload1 발행됨" 같은 주문 상태 기반 체크 추가. 어느 쪽이든 서버 쪽 변경만으로 가능하다.

- [ ] **`WorkRequestService.create()`에 조그 상호 배제 체크를 추가하는 구체 방식** (3장 B) — 작업요청 경로의 핵심 메서드를 직접 수정하는 것이 맞는지, 호출 전 별도 가드 레이어를 둘지. 그리고 3장 끝에 적은 레이스(세션 체크와 SQS produce 사이 시간차)를 이번에 손볼지, 엣지 케이스로 남길지.
- [ ] 조그 이력을 DB에 영속화할지(5장) — 지금은 "런타임 상태 + event_logs"로 충분하다고 제안했으나, 추후 조회/감사 필요성이 생기면 재검토.
- [ ] ROS 2 쪽 실제 조그 실행 API(`DSR_ROBOT2`의 어떤 함수를 쓸지), 좌표 응답 형식 — ROS 2 담당자와 7장 스키마 대조 필요.
- [ ] 스텝 크기·속도 상한값(9장)의 실측 기반 조정 — ROS 2 담당자 협의.
- [ ] 정지(TP-09) 요청의 실제 동작 범위(8.4) — ROS 2 쪽에서 진행 중 모션을 안전하게 중단할 수 있는지 확인.
- [ ] `motions.py`에 커밋된 병합 충돌 마커(별개 이슈, ROS 2 쪽)가 이 기능의 ROS 2 쪽 구현 착수 전에 해결되어야 하는지.
- [ ] 세션 소유권(한 번에 한 명만 조그 가능)을 어떻게 식별할지 — 로그인이 없는 현재 구조에서는 "활성화된 세션이 있으면 다른 탭/사용자는 거부" 정도의 단순 락으로 충분한지 확인 필요.

## 11. 작업 분해 제안

1. 백엔드: `teaching-pendant` 세션 런타임 상태(활성화 플래그) + `RobotTaskRepository.get_active_real_robot_task_locked` 신규 + `WorkRequestService.create()` 상호 배제 조건 추가 (3장).
2. 백엔드: `POST /api/teaching-pendant/session`·`/jog`·`/stop` 엔드포인트, SQS JOG 메시지 프로듀서(`SqsProducerService`에 `produce_jog_command` 추가하는 방식 제안 — 기존 `produce_load_command` 등과 같은 패턴).
3. 백엔드: `robot-events`의 `jog_complete`/`jog_failed` 컨슈머 처리(기존 `sqs_consumer_service.py` 확장) + 웹소켓 브로드캐스트.
4. 프론트: 티칭 팬던트 패널(아토믹 디자인 — atoms: 방향키 버튼·그리퍼 버튼, molecules: 축별 +/- 쌍, organisms: 조그패드/기준좌표계 선택/모드 전환/현재위치표시/그리퍼 컨트롤, 통합 패널). 활성화 안전 확인 모달.
5. 프론트: 스텝 상호 배제(이전 응답 전 버튼 비활성화), 타임아웃·에러 표시.
6. (ROS 2 담당자 협의) `robot-commands`의 `JOG`/`GRIPPER` 메시지 소비 + `DSR_ROBOT2` 조그 실행·`grip_open()`/`grip_close()` 호출 + `robot-events` 응답 발행.
7. 통합 테스트: 활성화 거부(작업 중), 정상 조그 1스텝, 조그 실패, 그리퍼 열기/닫기 성공·실패, 타임아웃, 세션 중 작업요청 load 보류 확인.

## 12. 구현 현황 (2026-11-17)

1~5단계(§11)와 7단계(백엔드 단위/API 테스트) 1차 구현 완료. 6단계(ROS 2 쪽 실제 조그/그리퍼 실행)는 범위 밖으로 남아 있다.

- **백엔드**: `enums.py`(`JogSpace`/`JogRefFrame`/`GripperAction` — DB 비영속, 런타임/스키마 전용), `core/runtime.py`(`TeachingPendantSession` dataclass + `teaching_pendant_lock`, DB 테이블 없음), `repositories/robot_task_repository.py`(`get_active_real_robot_task_locked` 신규), `services/teaching_pendant_service.py`(신규 — 세션 활성화/비활성화, 조그/그리퍼 요청, 정지, robot-events 완료/실패 처리, 타임아웃 스윕), `services/work_request_service.py`(`create()`에 조그 세션 체크 추가 — 베드 확인보다 먼저, 활성 중이면 주문 WAITING 유지 후 즉시 반환), `services/sqs_producer_service.py`(`produce_jog_command`/`produce_gripper_command` 추가, `MessageGroupId="jog"`), `services/sqs_consumer_service.py`(`jog_complete`/`jog_failed`/`gripper_complete`/`gripper_failed` 분기 추가), `api/routers/teaching_pendant.py`(신규, 4개 엔드포인트), `schemas.py`(DTO 6종), `main.py`(라우터·타임아웃 스윕 백그라운드 태스크 연결). 신규 테스트 24건(`tests/test_teaching_pendant.py` 17 + `tests/test_teaching_pendant_api.py` 7) 전부 통과, 기존 테스트 포함 전체 49건 통과(`pytest`로 재검증).
- **프론트**: `#/teaching-pendant` 라우트(`App.tsx`), `pages/TeachingPendantPage.tsx` + 신규 템플릿/오거니즘/몰리큘/아톰(`TeachingPendantTemplate`, `TeachingPendantActivationPanel`, `TeachingPendantSafetyModal`, `JogModeControls`, `JogPad`, `GripperControls`, `RobotPoseStatusPanel`, `StopControl`, `JogAxisControl`, `StepButton`), `lib/api.ts`(`enableTeachingPendant`/`disableTeachingPendant`/`sendJog`/`sendGripper`/`stopTeachingPendant` + `TeachingPendantError`), `hooks/useLiveState.ts`(`teaching_pendant.*` 5종 이벤트 처리 + 상태 노출), `types.ts`(조그 관련 타입 추가). `tsc --noEmit`·`vite build` 통과.
- `app/ros2_ws`는 건드리지 않음 (ROS 2 담당자 영역).
- **2026-11-18:** 가상 로봇 제거와 함께 `TeachingPendantPage`의 버튼 비활성화 조건에서 `bridge_connected`/`RobotState` 의존을 없앴다 (세션 활성 + 서버 연결만 본다). `RobotPoseStatusPanel`의 연결 표시는 "서버 연결됨/끊김"만 남겼다.

### 구현 중 PRD 원문과 다르게 간 부분 / 10장 미결 사항 중 실제로 결정한 것

- **정지(TP-09/8.4)**: ROS 2 쪽 STOP용 SQS 메시지 스키마가 PRD 7장에 없어서, 서버가 보장할 수 있는 범위(세션 비활성이면 409, 활성이면 한계 고지 메시지만 반환)까지만 구현했다. ROS 2 쪽에 실제 정지 신호를 보내는 신규 메시지 타입은 추가하지 않음 — ROS 2 담당자와 스키마 협의 후 추가해야 한다.
- **세션 소유권**: `enable_session(owner=...)` 파라미터는 있지만, PRD 6장의 `/session` 요청 바디가 `{enable: bool}`뿐이라 실제로는 항상 `owner=None`으로 호출된다. "활성화된 세션이 있으면 거부"라는 단순 락만으로 충분하다고 보고 세션 식별 자체는 미구현으로 남겼다(10장 미결 그대로).
- **레이스 방지**: 3장 끝에 적어둔 대로, 세션 체크와 SQS produce 사이의 레이스는 추가 락 없이 엣지 케이스로 남겼다.
- **DB 영속화**: 5장 결정(새 테이블 없음)을 그대로 따름, Alembic 마이그레이션 없음.
- **타임아웃**: PRD의 예시값 "10초"를 상수로 그대로 사용, 스윕 주기는 기존 `settings.timer_sweep_interval_sec`(0.5초) 재사용.

### 아직 안 한 것

- ROS 2 쪽 `robot-commands`의 `JOG`/`GRIPPER` 메시지 소비, 실제 `DSR_ROBOT2` 조그 실행·`grip_open()`/`grip_close()` 호출, `robot-events` 응답 발행, STOP 신호 전달 방식 — 전부 ROS 2 담당자 영역.
- 실제 백엔드+프론트 통합 기동 후 API/웹소켓 왕복 수동 확인(이번엔 각각 단위/타입체크/빌드까지만 확인함).
- 스텝 크기·속도 상한값의 ROS 2 쪽 실측 기반 조정.
