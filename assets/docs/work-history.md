# 작업 히스토리

웹·서버(`app/backend`, `app/frontend`) 작업을 날짜별로 남긴다. 다음 작업을 시작할 때 **맨 위 항목의 "현재 상태"와 "다음 작업"부터 읽는다.** 새 작업은 위쪽에 날짜 항목을 추가한다.

기능 명세는 PRD가 기준이다: [`prd.md`](prd.md) · [`prd-work-request-sqs.md`](prd-work-request-sqs.md) · [`prd-teaching-pendant.md`](prd-teaching-pendant.md)

---

## 2026-11-18 — UNLOAD 2단계, 수령대, 가상 로봇 제거

### 현재 상태 (이어서 작업하기 전에 확인)

| 항목 | 상태 |
| --- | --- |
| 커밋 | **커밋 전.** 브랜치 `feat/andrew-7`, 마지막 커밋 `08a1cee web timer`. 이 날짜의 변경은 전부 작업 트리에만 있다 (스테이징도 안 함) |
| 백엔드 테스트 | `cd app/backend && .venv/bin/python -m pytest -q tests` → **67 passed** |
| 프론트 | `cd app/frontend && npx tsc --noEmit -p . && npx vite build` → 통과 |
| DB 마이그레이션 | 0006~0010 추가. **실제 MySQL에는 아직 적용 안 함** (오프라인 SQL 생성만 확인). `./scripts/run.sh`가 기동 시 `alembic upgrade head`를 실행한다 |
| DB 데이터 | 런칭 전이라 스키마가 바뀌면 `app/scripts/reset_db.sql`로 초기화해서 쓴다 (데이터 보존용 마이그레이션은 만들지 않는다) |
| 실제 기동 확인 | **안 함.** 서버+프론트를 띄워 화면과 SQS 왕복을 본 적은 없다 |

### 한 일

#### 1. UNLOAD 2단계 (unload1 → unload2)

- 출력 타이머가 끝나면 서버가 `unload1`(프린터에서 꺼내기)을 보낸다. 이전부터 있던 동작이다.
- **`success_unload1`을 받았을 때:** 주문 PRINT_DONE → UNLOADING, 프린터 DONE → EMPTY를 먼저 커밋한다. 그다음 빈 수령대를 골라 `unload2`를 보낸다.
  - 보내는 메시지: `{"type":"unload2","work_id":N,"receive_pos_id":1|2}`, dedup id는 `unload2-{work_id}`
- **`success_unload2`를 받았을 때:** 주문 READY_FOR_PICKUP, 수령대 OCCUPIED.
- **`fail_unload1`을 받았을 때:** 상태는 그대로 두고 "작업대에 베드를 확인하세요!" 알럿을 띄운다. "확인"을 누르면 `POST /api/work-requests/{id}/retry-unload`로 unload1을 다시 보낸다.
- 코드: `services/work_request_service.py`의 `handle_unload1_success`, `_dispatch_unload2`, `dispatch_pending_unload2`, `handle_unload2_success`, `handle_unload1_failed`, `retry_unload1`. 이벤트 분기는 `services/sqs_consumer_service.py`.

#### 2. 수령대 관리 (`receive_pos` 테이블)

- 수령대는 2칸이다. 상태 흐름: EMPTY → RESERVED(unload2 발행) → OCCUPIED(success_unload2) → EMPTY(수령하기).
- 빈 칸 중 **1번을 먼저** 쓰고, 1번이 차 있으면 2번을 쓴다 (사용자 확정 규칙).
- **두 칸이 모두 찼을 때:** `alert.receive_pos_full` 알럿을 띄운다. 주문은 "UNLOADING + `receive_pos_id` NULL"로 대기한다(로봇이 완성품을 들고 기다리는 상태).
- **수령하기를 누르면:** `OrderService.pick_up`이 수령대를 비운 뒤 `WorkRequestService.dispatch_pending_unload2()`를 호출한다. 대기 중인 주문 중 가장 오래된 것의 unload2를 자동으로 보낸다.
- `orders.receive_pos_id`는 "어느 칸에 놓였었는지" 이력용이다. 칸이 비었는지는 `receive_pos` 테이블만 보고 판단한다.
- 추가한 것: API `GET /api/receive-pos`, 웹 이벤트 `receive_pos.updated`, 서버 기동 시 1·2번 행 자동 생성(`core/bootstrap.py`), `reset_db.sql` 반영.

#### 3. 프론트

- **수령대 패널 통합:** `ReceivePosPanel`이 기존 `PickupPanel`을 흡수했다(`PickupPanel`은 삭제). 1·2번 칸이 고정으로 나오고, 칸마다 손님·모양·완료 시각과 수령하기 버튼을 보여준다.
- **새 모달:** `UnloadPickFailedModal`(확인 시 unload1 재시도), `ReceivePosFullModal`(자리가 나면 자동으로 닫힘).

#### 4. 가상 로봇 경로 전체 제거 (사용자 요청: "가상로봇 시뮬레이터 안 쓰니까 전체 제거")

- **폴더:** `app/virtual-robot/` 삭제.
- **백엔드:** `/ws/bridge`, `DispatcherService`, `BridgeProtocolService`, 시뮬레이터·장애 주입 API, `RobotState`와 런타임의 로봇·bridge 상태, `POST /api/orders`(수동 주문), 작업 타임아웃 스윕, 관련 설정값(`BRIDGE_TOKEN` 등)을 삭제했다.
- **프론트:** `TopBar`, `SimulatorControls`, `DebugPanel`, `lib/robotArm.ts`, 로봇 상태 이벤트 처리를 삭제했다.
- **실행 환경:** `docker-compose.yml`, `scripts/run.sh`, `scripts/setup.sh`, `.env.example`, `.gitignore`, `README.md`(루트·app)를 정리했다.
- **결과:** 주문은 이제 작업요청(SQS) 경로로만 만들어진다.

#### 5. 안 쓰는 DB 컬럼·값 제거 (런칭 전이라 DB 초기화 전제)

| 마이그레이션 | 내용 |
| --- | --- |
| 0006 | `orders.receive_pos_id` 추가 |
| 0007 | `receive_pos` 테이블 생성 |
| 0008 | `orders.source` 삭제 (모든 주문이 WORK_REQUEST뿐이라 의미 없음) |
| 0009 | `robot_tasks.type`, `event_logs.direction` 삭제 (둘 다 값이 하나만 남음) |
| 0010 | `orders.pickup_delay_sec`, `robot_tasks.last_phase`, `robot_tasks.error_code` 삭제, `printers.status`에서 `UNLOADING` 값 삭제 |

#### 6. unload2 수동 발행 API (테스트용)

- `POST /api/sqs/commands/unload2` `{work_id, receive_pos_id: 1|2}` → robot-commands에 unload2를 바로 보낸다. DB 상태는 건드리지 않는다. 같은 work_id로 반복 호출해도 매번 발행된다(재시도 토큰).
- 코드: `api/routers/sqs.py`, 스키마 `Unload2CommandRequest`. 테스트: `tests/test_sqs_api.py`.
- 테스트 수: 62 → **67 passed**.

#### 7. PRD 정리

- `prd.md`는 전체를 다시 썼다. 가상 로봇 단계 문서에서 실물 로봇 + SQS 구조 문서로 바꿨다.
- `prd-work-request-sqs.md`도 다시 썼다. LOAD·UNLOAD 2단계와 수령대를 넣고, 지난 결정은 "변경 이력" 표로 남겼다.
- `prd-teaching-pendant.md`는 가상 로봇 언급을 정리하고 아래 안전 빈틈을 기록했다.
- `wbs.md`는 **손대지 않았다.** 사용자가 나중에 직접 수정하기로 했다.

### 함께 고친 버그

| 버그 | 원인 | 수정 |
| --- | --- | --- |
| load1 실패 후 재시도한 명령이 큐에서 버려질 수 있음 | FIFO 큐는 같은 dedup id로 5분 안에 온 메시지를 버리는데, 재시도가 첫 전송과 같은 `load-{id}`를 썼다 | 재시도할 때는 dedup id 뒤에 `retry_token`을 붙인다. unload1 재시도도 같은 방식 |
| 실물 로봇만 쓸 때 티칭 팬던트 버튼이 항상 잠김 | 버튼이 가상 로봇 연결(`bridge_connected`)에 묶여 있었다 | 세션 활성 + 서버 연결만 보도록 변경 |
| 로봇이 120초 넘게 걸리면 success_load1이 무시됨 | 가상 로봇용 작업 타임아웃이 SQS LOAD 작업을 FAILED로 바꿔 버렸다 | 타임아웃 스윕 자체를 삭제 (타임아웃은 미결 사항으로 다시 설계) |

### 주요 결정 (왜 이렇게 했는지)

- **물리적 사실은 먼저 커밋한다.** success_load1·success_unload1처럼 로봇이 이미 무언가를 옮긴 경우, 다음 명령이 보내지는지와 상관없이 적재대·프린터 상태부터 확정한다. 그래야 발행에 실패해도 상태가 틀어지지 않는다.
- **명령 발행과 예약은 한 트랜잭션이다.** 발행에 실패하면 그 단계의 예약(적재대 층, 프린터, 수령대)을 롤백한다.
- **수령대는 테이블로 관리한다.** 처음에는 주문 상태에서 계산했지만, 사용자 요청으로 `receive_pos` 테이블을 기준으로 바꿨다.
- **`orders.receive_pos_id`는 남긴다.** 수령 후에도 "몇 번 칸에 놓였었는지" 남기는 이력용이다.
- **unload 단계는 `robot_tasks`에 기록하지 않는다.** 주문·프린터·수령대 상태로만 추적한다. 아래 안전 빈틈의 원인이기도 하다.

### 알려진 문제 (미해결)

- **⚠️ 티칭 팬던트 상호 배제가 UNLOAD 단계를 막지 못한다.** unload1·unload2 진행 중에도 조그 세션을 켤 수 있다. 반대로 조그 세션 중에도 load2·unload1·unload2가 그대로 발행된다. 원인은 `robot_tasks`가 LOAD만 기록하고, `is_session_active()`를 `WorkRequestService.create()`에서만 확인하기 때문이다. 사용자 결정으로 **일단 보류**했다. 자세한 내용은 `prd-teaching-pendant.md` 3장·10장.

### 다음 작업 (우선순위 순)

1. **확인하고 커밋하기**
   - `cd app && ./scripts/run.sh`로 띄운다(마이그레이션 0006~0010 자동 적용).
   - 필요하면 `docker compose exec -T mysql mysql -u root -proot printshop < scripts/reset_db.sql`로 DB를 초기화한다.
   - 대시보드의 수령대 패널·알럿 모달과 SQS 송수신(SQS 모니터 페이지)을 확인한다.
   - 기능별로 나눠 커밋한다. 사용자가 직접 커밋·푸시한다.
2. **빈 프린터가 없을 때 대기 후 자동 재개.** 지금은 success_load1 때 빈 프린터가 없으면 로그만 남기고 멈춘다. success_unload1로 프린터가 비는 시점에 load2를 자동으로 보내면 된다. 수령대의 "대기 → 재개" 방식(`dispatch_pending_unload2`)을 그대로 쓰면 된다.
3. **WAITING 주문 재발행.** 적재대가 비었거나 조그 세션 중이어서 WAITING으로 남은 주문을, "채우기 완료"나 세션 종료 때 다시 보낼지 정한다.
4. **ROS 2 담당자와 맞출 것**
   - `sfarm_bridge`가 unload2의 `receive_pos_id`를 읽도록 수정
   - 테스트용으로 고정된 위치 값을 실제 값으로 바꾸기: load의 `start_pos_id=3`, load2·unload1의 `sd_pos_id=3`. 코드에서 `TODO: ... 3으로 하드코딩`을 검색하면 나온다
   - `fail_load2`, `fail_unload2`가 오면 무엇을 할지
5. **로봇 무응답 타임아웃.** 단계별로 따로 설계한다. `TaskStatus.FAILED`/`CANCELED`를 여기서 쓸지도 함께 정한다.
6. 티칭 팬던트 UNLOAD 상호 배제 (보류 중, 위 알려진 문제).
7. `wbs.md` 갱신 (사용자가 직접).

### 변경 파일 요약

- **새로 만든 파일:**
  - `app/backend/app/api/routers/receive_pos.py`, `app/backend/app/repositories/receive_pos_repository.py`
  - 마이그레이션 `0006`~`0010`
  - `app/frontend/src/components/organisms/ReceivePosPanel.tsx`, `ReceivePosFullModal.tsx`, `UnloadPickFailedModal.tsx`
  - 이 문서
- **삭제한 파일:**
  - `app/virtual-robot/` 전체
  - 백엔드 `bridge_ws.py`, `dispatcher_service.py`, `bridge_protocol_service.py`, `simulator_service.py`, `debug_service.py`, `routers/simulator.py`, `routers/debug.py`, `tests/test_dispatcher.py`
  - 프론트 `TopBar.tsx`, `SimulatorControls.tsx`, `DebugPanel.tsx`, `PickupPanel.tsx`, `lib/robotArm.ts`
- **수정한 파일:**
  - 백엔드: `models.py`, `enums.py`, `schemas.py`, `main.py`, `core/*`, 서비스, 레포지토리, 테스트
  - 프론트: `types.ts`, `lib/api.ts`, `hooks/useLiveState.ts`, `DashboardPage`, `TeachingPendantPage`, `PrinterPanel`, `RobotPoseStatusPanel`, `ConnectionStatus`, `DashboardTemplate`, `styles.css`
  - 스크립트·설정: `docker-compose.yml`, `run.sh`, `setup.sh`, `reset_db.sql`, `.env.example`, `.gitignore`
  - 문서: README 2개, PRD 3개

전체 목록은 `git status`로 확인한다.
