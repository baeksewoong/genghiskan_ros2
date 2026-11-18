# PRD — 웹 티칭 팬던트: ROS 2 쪽 실제 조그/그리퍼 실행

작성일: 2026-11-18 · 작성자: ROS 2 담당 에이전트(Claude 보조 작성)

> **이 문서의 위치:** 이 문서는 `assets/docs/prd-teaching-pendant.md`(이하 "부모 PRD")의
> **11장 6단계**("ROS 2 담당자 협의 — `robot-commands`의 `JOG`/`GRIPPER` 메시지 소비 +
> `DSR_ROBOT2` 조그 실행·`grip_open()`/`grip_close()` 호출 + `robot-events` 응답 발행")를
> 구체화한다. 백엔드(FastAPI)와 프론트엔드는 이미 구현되어 있고 건드리지 않는다
> (부모 PRD 12장 "구현 현황" 참고). 이 문서가 다루는 범위는 **`sfarm_interfaces`
> 신규 인터페이스 정의, `sfarm_bridge` 변경, `sfarm_robot` 변경**뿐이다.
>
> **문서 성격:** 이 PRD는 코드 구현 전 설계 문서다. 설계 중 사용자 판단이 필요했던
> 지점(5장 STOP 채널)은 **사용자가 옵션 A(전용 Standard SQS 큐)로 확정**했고,
> 실제 큐(`robot-commands-stop`)도 2026-11-18 생성 완료했다 — 5.2 참고.

관련 문서: `assets/docs/prd-teaching-pendant.md`(부모 PRD),
`assets/docs/prd-work-request-sqs.md`(`robot-commands`/`robot-events` 기존 스키마 기준),
`app/ros2_ws/src/sfarm_bridge`·`sfarm_robot`(이 문서가 수정 대상으로 삼는 코드)

---

## 1. 배경과 목적

부모 PRD 1~9장이 정의한 조그(jog)·그리퍼 개폐 기능은 웹 → FastAPI 백엔드 →
`robot-commands.fifo`(SQS) → **ROS 2(여기)** → `robot-events`(SQS) → 백엔드 →
웹소켓 순으로 왕복한다. 백엔드 쪽(`JogSpace`/`JogRefFrame`/`GripperAction` enum,
`TeachingPendantService`, `produce_jog_command`/`produce_gripper_command`,
API/웹소켓)은 이미 구현되어 **`robot-commands.fifo`에 `JOG`/`GRIPPER` 메시지를
실제로 발행하고 있다** (부모 PRD 12장). ROS 2 쪽은 아직 이 메시지를 소비하지 않고,
실제 로봇 조그/그리퍼 실행도 없다.

### 범위

다룬다:
- `sfarm_interfaces`: `Jog.action`, `Gripper.action`, `JogStop.srv` 신규 정의
- `sfarm_bridge`: `robot-commands.fifo`의 `JOG`/`GRIPPER` 메시지 소비(기존
  `parse_task_command`/`handle_message` 패턴 확장) + 신규 STOP 채널 소비 +
  `robot-events`에 `jog_complete`/`jog_failed`/`gripper_complete`/`gripper_failed` 발행
- `sfarm_robot`: `robot_action_server.py`에 Jog/Gripper 액션 서버 + `/sfarm/jog/stop`
  서비스 추가(기존 `busy_lock`/`goal_callback` 재사용), `motions.py`에 `run_jog()`/
  `run_gripper()` 설계

다루지 않는다: 백엔드/프론트(이미 끝남), 연속 조그, 티칭 포인트 저장, 그리퍼
파지 피드백(부모 PRD 1장 범위 밖과 동일).

### 전제 조사 결과 (설계에 반영한 사실들)

- **`motions.py`의 병합 충돌 마커는 이미 해소돼 있다.** `grep`으로 직접 확인했고
  (`<<<<<<<`/`=======`/`>>>>>>>` 없음), `git log -- motions.py`로 보면
  `6e7b685 conflict merge` 커밋에서 해소된 뒤 `7695382`~`7416445` 커밋까지
  정상적으로 이어져 왔다. 이 기능(ROS 2 조그) 착수 전에 별도로 손볼 필요는 없다
  — 부모 PRD 10장의 해당 미결 항목은 "해소됨, 재확인 불필요"로 닫을 수 있다.
- **`robot_action_server.py`의 `stop_requested` Event는 set/clear만 되고 실제로
  어디서도 `if self.stop_requested.is_set()` 체크나 `DSR_ROBOT2.stop()` 호출로
  이어지지 않는다** (`grep`으로 확인). 즉 지금 "정지"라고 부르는 것은 로그만 남기고
  응답만 보내는 **승인(acknowledge) 전용 플래그**이고, 실제로 로봇 모션을 멈추는
  효과는 없다. 이번 조그 기능의 STOP은 이 빈 틀을 실제로 채우는 첫 구현이 된다
  (5장).
- **DSR_ROBOT2의 상대 이동 지원 (두산 공식 DRL 매뉴얼 확인, 이 머신에 모듈 자체는
  설치돼 있지 않아 실제 설치본 대조는 못함 — 아래 "확인 필요" 참고):**
  `movej`/`movel`은 `mod`(`DR_MV_MOD_ABS`/`DR_MV_MOD_REL`, 기본 ABS)와
  `ref`(`DR_BASE`/`DR_WORLD`/`DR_TOOL`/사용자좌표계) 파라미터를 지원한다. 공식
  예제는 `movel(P3, time=5, ref=DR_TOOL, mod=DR_MV_MOD_REL)` 형태로, 지금 위치에서
  툴 좌표계 기준 상대 위치로 이동하는 것을 보여준다. ([movel 3.7.0](https://manual.doosanrobotics.com/en/programming-manual/3.7.0/publish/movel),
  [movej 3.4.0](https://manual.doosanrobotics.com/en/programming-manual/3.4.0/publish/movej),
  [movel 2.9 예제](https://manual.doosanrobotics.com/en/programming/2.9/Publish/movel))
- **정지 명령 (두산 공식 매뉴얼):** `stop(stop_mode)`가 있고 `DR_QSTOP`(Stop
  Category 2, 빠른 감속)·`DR_SSTOP`(소프트 스톱, 최대 감속시간의 약 1.5배로 더
  천천히)가 있다. `stop()`은 **모션만 멈추고 프로그램 실행 자체는 안 멈춘다**
  (DRL 프로그램 관점 — 우리는 DRL이 아니라 `DSR_ROBOT2` Python API를 쓰므로
  "프로그램 멈춤"은 해당 없음, 모션을 멈추는 효과만 가져오면 된다).
  ([stop 3.5.0](https://manual.doosanrobotics.com/en/programming-manual/3.5.0/publish/stop-st_mode))
- **확인 필요 (코드 작성 직전, 실제 로봇/시뮬레이터가 연결된 환경에서):**
  1. 이 레포에서 쓰는 `DSR_ROBOT2` 버전이 `movej`/`movel`의 `mod`/`ref` 키워드
     인자와 `DR_MV_MOD_REL`/`DR_MV_MOD_ABS`/`DR_WORLD`/`DR_TOOL`/`DR_QSTOP`/
     `DR_SSTOP`/`stop` 심볼을 실제로 `import` 가능한지 — 두산 매뉴얼은 버전별로
     갈려 있고(3.2~3.7, 2.9 등) 이 레포가 어느 버전 대응 패키지를 쓰는지 현재
     확인 못했다 (`find / -iname "DSR_ROBOT2*"`가 이 개발 머신에서는 빈 결과 —
     로봇 제어 PC에만 설치돼 있을 가능성이 높음).
  2. `stop()`이 **다른 스레드에서 진행 중인 `movel()`/`movej()` 블로킹 호출을
     실제로 중단시키는지** — `DSR_ROBOT2`의 모션 호출은 내부적으로 별도
     `dsr_node`를 통해 로봇 컨트롤러와 통신하므로(기존 `robot_action_server.py`
     주석 참고) 이론상 가능해 보이지만, 실측 확인 전에는 5장의 STOP 설계를
     "최선 노력(best-effort)"으로만 다뤄야 한다.

---

## 2. `sfarm_interfaces` 신규 인터페이스

기존 `Load1.action` 스타일(필드 중심, 간단한 Result/Feedback)을 따른다.
`sfarm_interfaces/CMakeLists.txt`의 `rosidl_generate_interfaces(...)` 목록에
`action/Jog.action`, `action/Gripper.action`, `srv/JogStop.srv`를 추가해야 한다.

### `action/Jog.action`

```
# Goal (입력) — 부모 PRD 7장 JOG 메시지 필드와 1:1 대응
string jog_id
string space        # "TASK" | "JOINT"
string ref_frame     # "BASE" | "TOOL"  (space=TASK일 때만 의미 있음, JOINT면 빈 문자열)
string axis          # TASK: "X"|"Y"|"Z"|"RX"|"RY"|"RZ", JOINT: "J1".."J6"
int8 direction        # 1 또는 -1
float64 step_size     # TASK 선형: mm, TASK 회전/JOINT: deg
---
# Result (출력)
bool success
string message
string jog_id
float64[6] posj
float64[6] posx
---
# Feedback
builtin_interfaces/Time start_at
builtin_interfaces/Time end_at
string jog_id
```

### `action/Gripper.action`

```
# Goal (입력)
string gripper_cmd_id
string action        # "OPEN" | "CLOSE"
---
# Result (출력)
bool success
string message
string gripper_cmd_id
string state          # "OPEN" | "CLOSE" (실행된 동작)
---
# Feedback
builtin_interfaces/Time start_at
builtin_interfaces/Time end_at
string gripper_cmd_id
```

### `srv/JogStop.srv`

기존 `Error.srv`(work_id 기반, Load/Unload 단계 실패 전용)와는 식별자 체계가
달라서(jog_id/gripper_cmd_id는 문자열, work_id는 정수) 재사용하지 않고 새로
만든다. 5장 STOP 설계에서 **"지금 진행 중인 동작이 jog/gripper일 때만 실제로
멈춘다"**는 스코프 제한을 응답에 드러낸다.

```
# Request
string reason   # 로그용, 비어 있어도 됨
---
# Response
bool success
string message
bool stopped_motion   # true = 실제로 stop() 호출함, false = 멈출 동작이 없었거나
                       #        LOAD/UNLOAD 중이라 무시함(8장 스코프 제한)
```

---

## 3. `sfarm_bridge` 변경 설계

### 3.1 JOG/GRIPPER 소비 (기존 `handle_message` 패턴 확장)

`parse_task_command()`는 지금 LOAD/LOAD2/UNLOAD1/UNLOAD2/UNLOAD만 분류한다.
`body.type == "JOG"` / `"GRIPPER"`인 메시지는 이 함수가 반환하는
`('LOAD'|...|None, fields)` 튜플 체계에 끼워 넣지 않고, `handle_message()` 맨
앞에서 **별도로 먼저 분기**한다(JOG/GRIPPER 필드는 LOAD/UNLOAD류와 구조가 달라
`parse_task_command`에 억지로 합치면 오히려 읽기 어려워진다):

```python
def parse_jog_or_gripper_command(command: dict) -> tuple[str | None, dict | None]:
    """'JOG'|'GRIPPER' 메시지를 goal 필드로. 해당 없으면 (None, None)."""
    raw_type = str(command.get('type') or '').strip().upper()
    if raw_type == 'JOG':
        required = ('jog_id', 'space', 'axis', 'direction', 'step_size')
        if not all(k in command for k in required):
            return None, None
        return 'JOG', {
            'jog_id': str(command['jog_id']),
            'space': str(command['space']).strip().upper(),
            'ref_frame': str(command.get('ref_frame') or '').strip().upper(),
            'axis': str(command['axis']).strip().upper(),
            'direction': int(command['direction']),
            'step_size': float(command['step_size']),
        }
    if raw_type == 'GRIPPER':
        if 'gripper_cmd_id' not in command or 'action' not in command:
            return None, None
        return 'GRIPPER', {
            'gripper_cmd_id': str(command['gripper_cmd_id']),
            'action': str(command['action']).strip().upper(),
        }
    return None, None
```

`handle_message()`는 `parse_task_command()` 호출 **전에** 이 함수를 먼저
시도한다(JOG/GRIPPER가 LOAD/UNLOAD 추론 로직을 타지 않도록). `execute_jog`/
`execute_gripper`는 기존 `execute_load1` 등과 완전히 같은 모양
(`ActionClient` + `wait_for_server` + `send_goal_async` + feedback/result 콜백 +
`action_timeout_sec` 폴링)으로 작성한다 — 새 패턴을 만들지 않고 기존 걸 그대로
복제-수정한다.

완료 시 `robot-events`로 보내는 이벤트는 부모 PRD 7장 스키마를 그대로 따른다:

```python
def build_jog_result_event(result: Jog.Result) -> dict:
    if result.success:
        return {'jog_id': result.jog_id, 'status': 'jog_complete', 'posx': list(result.posx)}
    return {'jog_id': result.jog_id, 'status': 'jog_failed',
            'error_code': 'EXECUTION_FAILED', 'message': result.message}

def build_gripper_result_event(result: Gripper.Result) -> dict:
    if result.success:
        return {'gripper_cmd_id': result.gripper_cmd_id, 'status': 'gripper_complete',
                'state': result.state}
    return {'gripper_cmd_id': result.gripper_cmd_id, 'status': 'gripper_failed',
            'error_code': 'EXECUTION_FAILED', 'message': result.message}
```

`produce()`는 수정 없이 그대로 쓸 수 있다(`MessageGroupId`는 기존처럼
`self.robot_id`, `MessageDeduplicationId`는 `jog_id`/`gripper_cmd_id`를 써서
`event_id` 대신 넣거나 `evt-{uuid4()}`를 그대로 써도 된다 — 부모 PRD는
`event_id` 필드를 요구하지 않으므로 기존 `produce()`의 `event.get('event_id')`
폴백이 `f'evt-{uuid.uuid4()}'`로 자연스럽게 떨어진다).

goal이 거절되는 경우(로봇이 LOAD/UNLOAD 중이라 `busy_lock`에 걸림, 7장 참고)의
처리는 기존 `execute_load1`과 동일 — `goal_handle.accepted is False`면
`holder['result']`가 `None`으로 남고, `handle_message()`는 "액션이 완료되지
않음, SQS 메시지를 삭제하지 않고 재시도용으로 남김" 분기를 타게 된다. 이건
**의도된 동작**이다: 조그 세션 중 LOAD/UNLOAD가 잘못 끼어들어 로봇이 바쁘면,
그 JOG/GRIPPER 명령은 조용히 사라지지 않고 다음 polling에서 재시도된다
(visibility timeout 이후 재수신). 부모 PRD 3장 "known gap"(백엔드가 UNLOAD
단계 중 조그 활성화를 못 막는 문제)에 대한 **ROS 2 쪽 2차 방어**가 된다 — 7장에서
더 설명한다.

### 3.2 신규 `GRIPPER`/`JOG` 그룹과 기존 LOAD 그룹의 분리

부모 PRD 7장이 이미 `MessageGroupId="jog"`로 LOAD(`"load"` 그룹 추정, 백엔드
`SqsProducerService` 쪽 — 이 문서에서 확인 안 함)와 분리해 발행하고 있다고
명시했다. `sfarm_bridge`의 `consume_loop()`는 `receive_message`에
`MessageGroupId` 필터를 걸지 않고 큐 전체를 순서대로 받으므로(FIFO 큐는
**같은 그룹 내에서만** 순서를 보장하고, 다른 그룹 메시지는 끼어들 수 있음),
JOG/GRIPPER와 LOAD/UNLOAD 메시지가 뒤섞여 들어올 수 있다는 점은 그대로 둔다 —
어차피 `goal_callback`의 `busy_lock` 거부가 실제 동시 실행을 막아주므로
(7장), 메시지 수신 순서 자체는 안전에 영향이 없다.

---

## 4. `sfarm_robot` 변경 설계

### 4.1 `robot_action_server.py`

- 생성자에 `run_jog`, `run_gripper` 콜러블을 주입받는 파라미터를 추가한다
  (기존 `run_load1` 등과 같은 방식).
- `JogServer = ActionServer(self, Jog, '/sfarm/jog', execute_callback=self.execute_jog, goal_callback=self.goal_callback, cancel_callback=self.cancel_callback, ...)`,
  `GripperServer`도 동일 패턴 — **`goal_callback`을 그대로 재사용**한다. 이게
  7장 상호배제의 핵심이다: 모든 액션 서버(Load1/Load2/Unload1/Unload2/Load/
  Unload/**Jog/Gripper**)가 같은 `self.busy_lock`을 보는 같은 `goal_callback`을
  쓰므로, 로봇이 어떤 동작 중이든 다른 동작의 goal은 자동으로 거절된다 — 새
  락을 만들 필요가 없다.
- **`self.current_action: str | None = None`**을 추가한다. `_execute()`
  계열 메서드가 `busy_lock`을 잡은 직후 `self.current_action = name`으로
  설정하고, 끝나면(`finally`) `None`으로 되돌린다. `/sfarm/jog/stop` 서비스
  핸들러가 "지금 멈춰도 되는 동작인지"(5장)를 판단하는 데 쓴다.
- `Jog`/`Gripper`의 Goal에는 `work_id`가 없으므로 기존 `_execute()`(내부에서
  `goal.work_id`/`result.work_id`를 직접 참조)를 그대로 재사용할 수 없다.
  구조는 그대로 베끼되 식별자 필드만 다른 `_execute_jog`/`_execute_gripper`
  전용 메서드를 작성한다(아래 의사코드). **(리팩터링 제안, 이번 범위는 아님):**
  `_execute()`를 `id_field: str` 파라미터로 일반화하면 넷을 하나로 합칠 수
  있다 — 지금은 안전하게 복제해서 쓰고, 추후 정리 과제로 남긴다.

```python
def execute_jog(self, goal_handle):
    goal = goal_handle.request
    result = Jog.Result(jog_id=goal.jog_id)
    feedback = Jog.Feedback(jog_id=goal.jog_id, start_at=self.get_clock().now().to_msg())
    with self.busy_lock:
        self.current_action = 'jog'
        try:
            goal_handle.publish_feedback(feedback)
            ok, posj_vals, posx_vals = self.run_jog(goal, log=self.get_logger().info)
        except Exception as exc:
            feedback.end_at = self.get_clock().now().to_msg()
            goal_handle.publish_feedback(feedback)
            goal_handle.abort()
            result.success, result.message = False, f'jog failed: {exc}'
            self.current_action = None
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
    return result
```

(`execute_gripper`도 같은 모양, `run_gripper`는 posj/posx 없이 `(ok, state)`만
돌려주면 된다.)

- `/sfarm/jog/stop` 서비스(5장)를 같은 `cb_group`에 추가한다.

### 4.2 `motions.py` — `run_jog()` 설계

**원칙(안전):** 기존 `_movel_checked()`의 "도달 확인" 패턴을 조그에도 적용한다
— 조그는 작은 스텝이라도 NOT REACHABLE일 수 있다(예: Joint 한계 근처). 대신
조그는 "들어 올린 상태 유지" 같은 후속 안전 요구가 없으므로, `_movel_checked`를
그대로 쓰기보다 **전용의 더 엄격한 검사**(이동 전 스텝 크기 상한 검증 +
이동 후 위치 오차 검사)를 둔다.

```python
# ---------------------------------------------------------------- 조그 (신규 상수)
# 조그는 힘 기반 안전장치(무게 감지, 걸림 감지)가 없는 자유공간 이동이라
# LOAD/UNLOAD 기본값보다 더 낮게 둔다 (부모 PRD 9장: "절반 이하" 권장보다 더 낮춤).
JOG_VELJ, JOG_ACCJ = 15.0, 15.0     # deg, deg/s^2  (기존 VELJ/ACCJ=30의 절반)
JOG_VELX, JOG_ACCX = 30.0, 30.0     # mm/s, mm/s^2  (기존 VELX/ACCX=100의 1/3 — 힘 감지 없음 고려)

# 부모 PRD 9장 상한과 동일 (안전 마진을 줄이지 않고, ROS 2 쪽에서 한 번 더 검증)
JOG_MAX_LINEAR_MM = 20.0
JOG_MAX_ROT_DEG = 15.0
JOG_MAX_JOINT_DEG = 15.0

_TASK_AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2, 'RX': 3, 'RY': 4, 'RZ': 5}
_JOINT_AXIS_INDEX = {f'J{i+1}': i for i in range(6)}
_REF_FRAME = {'BASE': DR_BASE, 'TOOL': DR_TOOL}  # DR_TOOL은 motions.py 상단 import에 추가 필요


class JogRejected(Exception):
    """스텝 상한 초과 등 실행 전 검증 실패 (모션 자체는 일어나지 않음)."""


def run_jog(goal, log=print) -> tuple[bool, list[float], list[float]]:
    """goal(space/ref_frame/axis/direction/step_size)을 실제 이동으로 변환.

    반환: (성공 여부, posj[6], posx[6]) — 실패해도 현재 위치는 돌려준다(웹 표시용).
    """
    space = goal.space
    axis = goal.axis
    step = abs(goal.step_size)
    direction = 1 if goal.direction >= 0 else -1

    if space == 'JOINT':
        if axis not in _JOINT_AXIS_INDEX:
            raise JogRejected(f'알 수 없는 JOINT 축: {axis}')
        if step > JOG_MAX_JOINT_DEG:
            raise JogRejected(f'JOINT 스텝 상한 초과: {step}deg > {JOG_MAX_JOINT_DEG}deg')
        delta = [0.0] * 6
        delta[_JOINT_AXIS_INDEX[axis]] = direction * step
        movej(posj(*delta), vel=JOG_VELJ, acc=JOG_ACCJ, mod=DR_MV_MOD_REL)

    elif space == 'TASK':
        if axis not in _TASK_AXIS_INDEX:
            raise JogRejected(f'알 수 없는 TASK 축: {axis}')
        idx = _TASK_AXIS_INDEX[axis]
        limit = JOG_MAX_LINEAR_MM if idx < 3 else JOG_MAX_ROT_DEG
        if step > limit:
            raise JogRejected(f'TASK 스텝 상한 초과 ({axis}): {step} > {limit}')
        ref = _REF_FRAME.get(goal.ref_frame)
        if ref is None:
            raise JogRejected(f'알 수 없는 ref_frame: {goal.ref_frame}')
        delta = [0.0] * 6
        delta[idx] = direction * step
        movel(posx(*delta), vel=JOG_VELX, acc=JOG_ACCX, ref=ref, mod=DR_MV_MOD_REL)

    else:
        raise JogRejected(f'알 수 없는 space: {space}')

    posj_vals, posx_vals = get_current_poses()
    return True, posj_vals, posx_vals
```

**확인 필요(위 1장에서 적은 것과 동일, 코드 작성 전 재확인):** `mod`/`ref`
키워드, `DR_MV_MOD_REL`, `DR_TOOL` 심볼이 실제 설치된 `DSR_ROBOT2`에서
`import` 가능한지.

**대안(위 확인이 실패할 경우의 Plan B — 매 축 "현재값 읽고 더해서 절대 이동"):**

```python
    # TASK, ref=BASE일 때만 단순하다 (TOOL 프레임은 현재 자세로 delta를 회전시켜야
    # 하므로 추가 변환 코드가 필요함 — 이 경우 mod=REL 네이티브 지원이 훨씬 안전함)
    cur = list(get_current_posx()[0])
    cur[idx] += direction * step
    movel(posx(*cur), vel=JOG_VELX, acc=JOG_ACCX, ref=DR_BASE)
```

Plan B는 `ref_frame=TOOL`을 올바로 지원하려면 회전 변환이 필요해 복잡도가
크게 늘어난다 — **Plan A(네이티브 `mod=REL`)가 가능하면 반드시 그걸 쓴다.**
Plan B로 가야 한다면, `ref_frame=TOOL` 조그는 1차 구현에서 제외하고
`ref_frame=BASE`만 먼저 내는 것도 고려할 수 있다(10장 미결 사항에 남김).

### 4.3 `motions.py` — `run_gripper()` 설계

이미 있는 `grip_open()`/`grip_close()`를 그대로 호출하면 된다 — 신규 모션
코드는 필요 없다:

```python
def run_gripper(goal, log=print) -> tuple[bool, str]:
    """goal.action('OPEN'|'CLOSE')에 따라 그리퍼 개폐. 항상 성공(True)으로 본다
    (파지 피드백은 부모 PRD 1장 범위 밖 — 디지털 출력을 내리는 것 자체는 실패할
    수 있는 지점이 거의 없음)."""
    action = goal.action
    if action == 'OPEN':
        grip_open()
    elif action == 'CLOSE':
        grip_close()
    else:
        raise ValueError(f'알 수 없는 gripper action: {action}')
    return True, action
```

---

## 5. STOP 설계 (가장 중요한 결정 — 사용자 확인 필요)

### 5.1 문제: 기존 `robot-commands.fifo`를 못 쓰는 이유 (조사로 발견)

부모 PRD 8.4는 "SQS는 이미 큐에 들어가거나 수신된 명령을 취소하는 기본 수단이
없다"고 썼는데, 이 문서를 쓰며 **그보다 더 근본적인 문제**를 발견했다.
`sfarm_bridge.consume_loop()`는 **완전히 순차적**이다:

```
receive_message() (최대 20초 롱폴링)
  -> handle_message() (액션 goal을 보내고 결과가 올 때까지 블로킹, 최대 action_timeout_sec=120초)
  -> (반복)
```

즉 지금 JOG 스텝이 실행되는 동안 브릿지의 수신 루프는 **다음 메시지를 받으러
가지도 않는다**. STOP 메시지를 똑같이 `robot-commands.fifo`(그룹 `"jog"`)에
넣으면, 그 STOP 메시지는 **지금 실행 중인 JOG 스텝의 결과가 돌아올 때까지
브릿지에 도착조차 하지 않는다** — "정지를 요청했는데 받았을 땐 이미 끝나
있었다" 정도가 아니라, 정지 요청 자체가 지연 전달되어 즉시성이 완전히 사라진다.

### 5.2 결정: 전용 채널 (옵션 A) — **확정, 큐 생성 완료**

**확정:** STOP은 `robot-commands.fifo`와 **분리된 전용 SQS 큐**로 보낸다.
사용자가 2026-11-18 Standard 큐를 생성 완료했다:

```
https://sqs.ap-northeast-2.amazonaws.com/135135392043/robot-commands-stop
```

FIFO가 아니라 Standard로 만든 이유(채팅에서 확인·확정): STOP은 순서가 중요하지
않은 단일 멱등 명령이다 — 여러 번 와도, 순서가 섞여도, 중복 전달돼도
`stop(DR_SSTOP)`을 한 번 더 호출하는 것뿐이라 무해하다. FIFO의
`MessageGroupId`/`MessageDeduplicationId` 관리는 이 경우 이점 없이 복잡도만
늘린다.

브릿지는 `consume_loop`과 **독립된 두 번째 백그라운드 스레드**
(`stop_consume_loop`, 짧은 `WaitTimeSeconds`, 예: 5초)로 이 큐를 긁는다. STOP이
도착하면 SQS 왕복 지연은 피할 수 없지만(이건 부모 PRD도 인정한 한계), 적어도
**"이미 처리 중인 JOG 메시지 뒤에 줄 서서 기다리는" 자체 지연은 없앨 수 있다.**

`DEFAULT_STOP_QUEUE_URL`로 `sfarm_bridge.py` 상단의 `DEFAULT_COMMAND_QUEUE_URL`/
`DEFAULT_EVENT_QUEUE_URL`과 같은 자리에 상수로 추가하고, 노드 파라미터
(`stop_queue_url`)로도 오버라이드 가능하게 한다(기존 두 큐와 동일한 패턴).

```
backend --(새 produce_jog_stop_command)--> robot-commands-stop (Standard SQS)
                                                      |
                                      sfarm_bridge.stop_consume_loop (전용 스레드)
                                                      |
                                      /sfarm/jog/stop 서비스 호출 (ROS 2, SQS 아님)
                                                      |
                                      robot_action_server: stop(DR_SSTOP) 시도 (4.1/2장)
```

**이 결정으로 남은 교차 팀 의존성(ROS 2 쪽 범위 밖, 이 문서에서 구현하지 않음):**
- 백엔드 쪽에 작은 추가 작업이 필요하다: `SqsProducerService`에
  `produce_jog_stop_command()` 추가(위 큐 URL로 발행) + `TeachingPendantService`의
  `/stop` 핸들러가 지금(부모 PRD 12장: "한계 고지 메시지만 반환")은 SQS를 전혀
  안 건드리는데, 이제 실제로 이 큐에 발행하도록 바꿔야 한다. 10장에 교차 팀
  의존성으로 남긴다.

**기각된 대안(옵션 B) — 새 인프라 없이 기존 큐 재사용:** STOP도
`robot-commands.fifo` 그룹 `"jog"`로 보내는 방안은 검토했으나 채택하지 않았다.
5.1에서 설명한 대로 **"진행 중인 스텝이 끝나야 정지 요청이 브릿지에 도착한다"**는
근본적 한계가 있어 — 사실상 "다음 스텝을 보내지 않게 막는" 효과만 남고(그마저도
이미 백엔드가 자체적으로 보장, 부모 PRD 8.4), ROS 2 쪽에 실제로 "지금 멈춰"를
전달하는 효과는 거의 없기 때문이다.

### 5.3 `/sfarm/jog/stop` 서비스 핸들러 (4.1에서 추가한 `current_action` 활용)

```python
def handle_jog_stop_service(self, request: JogStop.Request, response: JogStop.Response):
    if self.current_action not in ('jog', 'gripper'):
        response.success = True
        response.stopped_motion = False
        response.message = (
            '지금 로봇이 조그/그리퍼 동작 중이 아님'
            if self.current_action is None
            else f'로봇이 {self.current_action} 중이라 조그 정지 요청은 무시함'
        )
        return response
    try:
        stop(DR_SSTOP)   # motions.py가 아니라 이 서비스가 직접 호출 (busy_lock을 안 잡음 — 의도적)
        response.success = True
        response.stopped_motion = True
        response.message = 'stop(DR_SSTOP) 호출함'
    except Exception as exc:
        response.success = False
        response.stopped_motion = False
        response.message = f'stop() 호출 실패: {exc}'
    return response
```

**왜 LOAD/UNLOAD 중엔 무시하는가:** `stop()`은 액션 단위가 아니라 **로봇
컨트롤러 레벨**에서 동작한다 — 호출 시점에 로봇이 뭘 하고 있든 그 모션을
멈춘다. LOAD/UNLOAD의 `_insert_move`/`_wiggle_side`/`insert_sd` 등은 "걸리면
놓지 않고 멈춘다"는 자체 안전 설계를 갖고 있고, 중간에 순응 제어
(`task_compliance_ctrl`)가 걸려 있는 구간에서 외부 `stop()`이 끼어들면
`release_compliance_ctrl()` 짝 맞추기가 깨질 위험이 있다(시스템 프롬프트의
"안전 기본 원칙"이 명시적으로 지키라고 한 부분). 그래서 **조그 세션의 STOP은
LOAD/UNLOAD의 안전 시퀀스를 침범하지 않도록 jog/gripper 동작 중일 때만
작동**하도록 스코프를 좁혔다 — 이게 이 설계에서 안전상 가장 중요한 판단이다.

**이 설계가 보장하는 것과 못 하는 것 (부모 PRD 8.4 갱신):**
- 보장: 지금 진행 중인 동작이 jog/gripper라면, SQS 왕복 지연 이후 `stop(DR_SSTOP)`
  호출을 시도한다(성공 여부는 "확인 필요" 1장 2번 항목에 달려 있음 — 실측 전엔
  "시도"까지만 보장).
  보장: LOAD/UNLOAD 동작은 이 STOP으로 절대 중단되지 않는다(안전 설계 보존).
- 못 함: 로봇이 멈추는 "즉시성" — SQS 왕복(옵션 A라도 최소 수백 ms~수 초)과
  이미 시작된 아주 짧은 스텝(JOG_VELX=30mm/s 기준 20mm 스텝이면 약 0.7초)이
  겹치면 멈추기 전에 스텝이 끝날 수 있다. 이건 UI에 그대로 고지해야 한다
  (부모 PRD 8.4가 이미 요구한 문구 그대로 유효).

---

## 6. 비기능 요구사항 (안전/속도) — 확정 제안

| 항목 | 값 | 근거 |
| --- | --- | --- |
| `JOG_VELJ`/`JOG_ACCJ` | 15.0 / 15.0 (deg, deg/s²) | 기존 `VELJ=ACCJ=30`의 절반. 조그는 힘 기반 안전장치가 없는 자유공간 이동이라 LOAD/UNLOAD보다 더 신중하게 |
| `JOG_VELX`/`JOG_ACCX` | 30.0 / 30.0 (mm/s, mm/s²) | 기존 `VELX=ACCX=100`의 약 1/3. 부모 PRD 9장의 "절반 이하" 권장보다 더 낮춤 — 조그는 매 스텝이 사람이 직접 보고 누르는 동작이라 과속보다 "느리지만 예측 가능"이 우선 |
| `JOG_MAX_LINEAR_MM` | 20.0 | 부모 PRD 9장 그대로(마진 변경 없음), ROS 2 쪽에서 이중 검증(4.2) |
| `JOG_MAX_ROT_DEG` / `JOG_MAX_JOINT_DEG` | 15.0 / 15.0 | 〃 |
| 그리퍼 | 변경 없음 (`grip_open`/`grip_close`, `wait(1.5)`) | 기존 안전장치(무게감지는 LOAD 쪽에만 있고 조그엔 없음) 그대로 재사용, 범위 밖(1장) |

이 속도값들은 **시뮬레이터/실기 실측 전 제안값**이다 — 실제 적용 전 가상
로봇(DRCF)에서 먼저 돌려보고, 이상하면(너무 느려 쓰기 불편하거나, 생각보다
빨라 보이는 등) 조정한다. 속도/가속도를 더 올리는 방향으로 조정할 때는 왜
올리는지, 안전 마진이 줄어드는지 반드시 짚고 넘어간다(시스템 프롬프트 안전
원칙).

---

## 7. 상호배제 (busy_lock 공유 + 부모 PRD 3장 known gap 완화)

4.1에서 설명한 대로 Jog/Gripper 액션 서버가 기존 `goal_callback`
(`self.busy_lock.locked()` 체크)을 그대로 쓰면:

- **로봇이 LOAD/UNLOAD 중 → JOG/GRIPPER goal 거절.** 거절된 goal은 브릿지의
  `execute_jog`/`execute_gripper`에서 `result=None`으로 돌아오고, `handle_message()`는
  SQS 메시지를 지우지 않고 재시도용으로 남긴다(3.1). 결과적으로 "조그 명령이
  씹히지 않고 나중에 재시도된다" — 실패를 삼키지 않는다는 기존 설계 원칙과
  일치한다.
- **로봇이 JOG/GRIPPER 중 → LOAD/UNLOAD goal 거절.** 이게 바로 **부모 PRD 3장의
  "known gap"(백엔드가 UNLOAD1/UNLOAD2/LOAD2 발행을 조그 세션 중에도 막지
  못함)에 대한 ROS 2 쪽 2차 방어**다. 백엔드가 실수로 unload1을 발행해도,
  로봇이 지금 조그 중이면 그 goal은 `goal_callback`에서 바로 거절되고,
  `sfarm_bridge`는 (기존 `execute_unload1` 로직 그대로) "goal was rejected"를
  로그로 남기고 **`call_load_stop_service`를 부르지 않는 채로**(실패가 아니라
  거절이므로) SQS 메시지를 지우지 않고 재시도한다. 조그가 끝나면 다음 polling에서
  자연히 재시도되어 unload1이 정상 진행된다 — **로봇이 두 동작을 동시에 받는
  최악의 상황(안전 문제)은 막히고, 최악의 경우 unload1이 조그가 끝날 때까지
  지연되는 정도**로 완화된다. 이건 부모 PRD 3장의 빈틈을 "닫는다"가 아니라
  "안전 측면에서 완화한다"는 뜻이다 — 백엔드 쪽 근본 해결(부모 PRD 10장 해결
  방향 후보)은 여전히 필요하다. 이 문서에서는 **백엔드를 고치지 않고도 ROS 2
  쪽 변경만으로 이 완화 효과가 자연히 따라온다**는 점을 명시해 둔다.
- 새 락을 만들지 않았다 — 기존 `busy_lock`/`goal_callback` 재사용만으로 요구된
  "로봇은 한 번에 하나" 규칙이 LOAD/UNLOAD/JOG/GRIPPER 전체에 적용된다.

---

## 8. 기능 요구사항 (ROS 2 쪽)

| ID | 기능 | 상세 | 우선순위 |
| --- | --- | --- | --- |
| RJ-01 | 인터페이스 정의 | `Jog.action`/`Gripper.action`/`JogStop.srv` 추가, `CMakeLists.txt` 갱신 (2장) | P0 |
| RJ-02 | 브릿지: JOG 소비 | `parse_jog_or_gripper_command` + `execute_jog`(기존 `execute_load1` 패턴 복제) (3.1) | P0 |
| RJ-03 | 브릿지: GRIPPER 소비 | 〃 `execute_gripper` (3.1) | P0 |
| RJ-04 | 브릿지: STOP 전용 채널 | 신규 큐(`robot-commands-stop`, 생성 완료) + `stop_consume_loop` 스레드(5.2) | P1 |
| RJ-05 | 로봇 서버: Jog 액션 서버 | 기존 `busy_lock`/`goal_callback` 공유, `current_action` 추적 (4.1) | P0 |
| RJ-06 | 로봇 서버: Gripper 액션 서버 | 〃 | P0 |
| RJ-07 | 로봇 서버: `/sfarm/jog/stop` 서비스 | `current_action` 스코프 제한 적용 (5.3) | P1 |
| RJ-08 | `motions.py`: `run_jog()` | 상대 이동 변환 + 스텝 상한 이중 검증 (4.2) | P0 |
| RJ-09 | `motions.py`: `run_gripper()` | `grip_open`/`grip_close` 재사용 (4.3) | P0 |
| RJ-10 | `robot-events` 응답 발행 | `jog_complete`/`jog_failed`/`gripper_complete`/`gripper_failed` (3.1) | P0 |
| RJ-11 | 로깅/추적성 | 각 단계 `get_logger()` 로그 (기존 LOAD/UNLOAD와 같은 수준) | P1 |

---

## 9. 미결 사항 / 확인 필요 (요약)

- [x] **(결정됨, 2026-11-18)** 5.2의 STOP 채널 — 옵션 A(전용 Standard SQS 큐)로
  확정. 큐 `robot-commands-stop` 생성 완료. 남은 교차 팀 의존성: 백엔드
  `produce_jog_stop_command()` 추가(5.2).
- [ ] **(실측 필요)** `DSR_ROBOT2`의 실제 설치 버전이 `movej`/`movel`의
  `mod`/`ref` 파라미터와 `DR_MV_MOD_REL`/`DR_TOOL`/`DR_QSTOP`/`DR_SSTOP`/`stop`
  심볼을 지원하는지 (1장 "확인 필요", 4.2 Plan A/B 분기 결정에 직결).
- [ ] **(실측 필요)** `stop()`이 다른 스레드의 진행 중인 `movel()`/`movej()`를
  실제로 중단시키는지 — 5.3의 "최선 노력" 수준을 실제로 어디까지 보장할 수
  있는지 결정됨.
- [ ] `ref_frame=TOOL`을 Plan B(상대 이동 네이티브 미지원 시 폴백)로 구현해야
  하는 경우, 회전 변환 코드가 필요해 복잡도가 커짐 — 1차 구현에서
  `ref_frame=BASE`만 내고 TOOL은 후속으로 미룰지 결정 필요.
- [ ] `_execute()`를 Load/Unload/Jog/Gripper 공통으로 일반화하는 리팩터링
  (4.1 "리팩터링 제안") — 이번 범위는 아니고, 넷의 중복 코드가 쌓이면 재검토.
- [ ] RJ-04(STOP)의 우선순위를 P1로 뒀다 — RJ-01~03/05~06/08~10(P0)만으로도
  "조그 1스텝 실행 + 완료 응답"은 동작하므로, STOP 없이 먼저 통합 테스트하고
  STOP을 이어서 붙이는 단계적 진행이 가능하다(11장).

## 10. 작업 분해 제안

1. `sfarm_interfaces`: `Jog.action`/`Gripper.action`/`JogStop.srv` 추가,
   `CMakeLists.txt` 갱신, `colcon build --packages-select sfarm_interfaces` 확인.
2. `sfarm_robot`: `motions.py`에 `run_jog()`/`run_gripper()` (DSR_ROBOT2
   확인 필요 항목을 먼저 가상 로봇에서 검증), `robot_action_server.py`에
   Jog/Gripper 액션 서버 + `current_action` 추가. STOP 서비스는 이 단계에서
   빼고 RJ-01~03/05~06/08~10만으로 먼저 끝까지 동작 확인.
3. `sfarm_bridge`: `parse_jog_or_gripper_command` + `execute_jog`/
   `execute_gripper` + 이벤트 빌더. 가상 로봇 대상으로 웹 → SQS → ROS 2 →
   SQS → 웹 왕복을 수동 테스트(부모 PRD 11.7 패턴과 동일).
4. STOP: `robot-commands-stop` 큐(생성 완료, 5.2)를 읽는 브릿지
   `stop_consume_loop` + 로봇 서버 `/sfarm/jog/stop` 서비스. (교차 팀: 백엔드가
   `produce_jog_stop_command()`로 이 큐에 발행하도록 추가해야 전체 왕복이 완성됨.)
5. 안전 상한값(6장) 실측 기반 조정 — 가상 로봇에서 먼저, 실기는 반드시 사용자
   승인 후에만.
6. 통합 테스트: 정상 조그 1스텝(TASK/JOINT × BASE/TOOL), 그리퍼 열기/닫기,
   스텝 상한 초과 거부, LOAD/UNLOAD 중 조그 거절(7장), 조그 중 LOAD/UNLOAD
   거절(7장), STOP(옵션 선택에 따라).
