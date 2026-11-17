# `Unload1` 연동 관련 기능 개발자 확인 사항

`unload.py` 및 최신 `poses.py`(`UNLOAD_J`, `UNLOAD_PRE_J`, `UNLOAD_LAYER_STEP`, `UNLOAD_BRANCH_FROM`) 기준으로 `motions.py`의 `run_unload1()`을 모든 층(`1, 2, 3`)에 대해 동작하도록 반영했습니다.  
실기 테스트 및 `Unload2` 연동 전에 아래 사항을 확인 부탁드립니다.

---

## 1. 파지 실패(`grab_pull` → `False`) 시 로봇 복귀 위치
- **현재 구현 (`unload.py` / `motions.py` `unload_grab_pull`)**:
  - 끝까지 당겨도 턱 걸림(`|dFx| >= 0.7N`)이 감지되지 않으면 **원위치(프린터 층 내부 좌표)로 되돌아가 그리퍼를 열고(`grip_open`) `False`를 반환**한 채 멈춥니다.
- **확인할 점**:
  - `Unload1` 액션이 `False`로 실패 종료될 때, 로봇 팔이 **프린터 내부 원위치에 머물러도 되는지**, 아니면 **`unload_leave_layer(layer)` → `진입전2` → `home`까지 빠져나온 뒤 `False`를 반환**해야 하는지 확인이 필요합니다.

## 2. `Unload1` 시작 시 그리퍼 열기(`grip_open()`) 여부
- **현재 구현 (`motions.py` `run_unload1`)**:
  - 수동 스크립트(`unload.py`)에는 없던 동작이나, 자동 액션 실행 시 이전 작업 상태로 그리퍼가 닫혀 있을 수 있어 **`1`번(`home`) 이동 직후 `grip_open()`을 호출**하도록 넣었습니다.
- **확인할 점**:
  - `Unload1` 진입 시 `1`번(`home`)에서 그리퍼를 여는 동작이 다른 공정과 충돌할 여지가 없는지 확인 부탁드립니다.

## 3. `Unload1` 성공 이후(`Unload2` 인계) 경로 확인
- **현재 동작**:
  - `Unload1` 성공 시 위치 제어 `-160mm` + 순응 제어 최대 `-10mm` 당긴 위치에서 `release_compliance_ctrl()` 후 **베드판을 잡은 채 정지**합니다.
- **확인할 점**:
  - `Unload2`가 이 상태에서 이어받을 때, 바로 **`unload_leave_layer(layer)`(또는 `진입전2` / `home`)로 이동해도 프린터 프레임/턱과 간섭이 없는지**, 아니면 `-X`로 추가 후진(`pull_out`)이 필요한지 확인이 필요합니다.

## 4. 전 층(`1, 2, 3층`) 실기 당김 거리 및 힘 임계값 검증
- **현재 파라미터 (`motions.py`)**:
  - `UNLOAD_PULL_POS_MM = 160.0`
  - `UNLOAD_PULL_COMPLIANCE_MM = 10.0`
  - `UNLOAD_CATCH_FORCE_N = 0.7`
  - `COMPLIANCE_STX = [500, 3000, 3000, 200, 200, 200]`
- **확인할 점**:
  - `1, 2, 3층` 각각에서 `-X`로 `160~170mm` 당길 때 `NOT REACHABLE`이나 관절 한계(`J3`)에 걸리지 않는지, 그리고 모든 층에서 `UNLOAD_CATCH_FORCE_N = 0.7N`으로 정상/실패 구분이 안정적으로 되는지 실기 확인이 필요합니다.

## 5. `poses.py` 내 레거시 코드 주석 블록 정리 여부
- **현황 (`poses.py` 1~127행)**:
  - 파일 상단 1~127행이 `#------------ 위는 레거시 코드` 형태로 전체 주석 처리된 채 남아 있습니다.
- **확인할 점**:
  - 추후 혼동 방지를 위해 해당 주석 블록을 삭제해도 되는지 확인 부탁드립니다.

## 6. 기타 ROS 2 연동 체크포인트
- **`Unload1.Feedback` 발행 주기 (`robot_action_server.py`)**:
  - 현재 `posj`, `posx`, `start_at`, `end_at`, `work_id` 피드백은 **액션 시작 직전 1회, 종료 직후 1회**만 발행됩니다. 모션 중 실시간 피드백이 필요한지 확인이 필요합니다.
- **`setup.py` 엔트리포인트**:
  - `sfarm_robot/setup.py`의 `console_scripts`에 `unload = sfarm_robot.unload:main`이 아직 등록되어 있지 않습니다(`ros2 run sfarm_robot unload` 실행을 원하면 추가 필요).
- **`/sfarm/unload2` 서버 미구현**:
  - `sfarm_bridge`에는 `Unload2` 클라이언트가 있으나 `robot_action_server.py`에는 아직 `/sfarm/unload2` 액션 서버가 등록되어 있지 않습니다.
