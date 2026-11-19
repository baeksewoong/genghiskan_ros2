# 작업 히스토리

웹·서버(`app/backend`, `app/frontend`) 작업을 날짜별로 남긴다. 다음 작업을 시작할 때 **맨 위 항목의 "현재 상태"와 "다음 작업"부터 읽는다.** 새 작업은 위쪽에 날짜 항목을 추가한다.

기능 명세는 PRD가 기준이다: [`prd.md`](prd.md) · [`prd-work-request-sqs.md`](prd-work-request-sqs.md) · [`prd-teaching-pendant.md`](prd-teaching-pendant.md)

---

## 2026-11-19 — 작업요청(SQS) 로직 리뷰·수정 + 수동 테스트 현황 문서화

### 현재 상태 (이어서 작업하기 전에 확인)

| 항목 | 상태 |
| --- | --- |
| 커밋 | **커밋 전.** 브랜치 `fix/andrew-10`, 마지막 커밋 `b55ee58 백엔드 로직 수정 중`. 이 날짜의 변경은 전부 작업 트리에만 있다 (`git status`로 변경 파일 확인) |
| 백엔드 테스트 | `cd app/backend && .venv/bin/python -m pytest -q` → 70개 전체 통과 |
| 프론트 | 건드리지 않음 |
| 로컬 서버 | uvicorn(`--reload`, port 8000) + MySQL(docker `app-mysql-1`) 계속 띄워둔 상태. **주의:** `.env`에 실제 AWS SQS 큐(COMMAND_QUEUE_URL/EVENT_QUEUE_URL)가 설정돼 있고, ROS2 쪽에 명령 발행 후 150ms 내로 success_*를 자동 응답하는 뭔가가(모킹/스텁으로 보임) 떠 있다 — 작업요청을 만들면 실제로 AWS까지 왕복한다 |
| 수동 테스트 현황 | [`test-plan-work-request-sqs.md`](test-plan-work-request-sqs.md) — 37개 전부 완료. 마지막 G섹션 3건(31·32·33번)은 로봇 점유 창이 수백ms라 손으로 못 맞춰서, 작업요청 생성 응답/상태 폴링 직후 조그 세션 활성화를 쏘는 레이스 스크립트로 재현(`/private/tmp/.../scratchpad/test3{1,2}_race.py`, 세션에만 존재 — 필요하면 재작성) |

### 한 일

1. **하드코딩 제거**: `sqs_producer_service.py`/`work_request_service.py`/`timer_service.py`에서 테스트용으로 박아뒀던 `start_pos_id=3`, `sd_pos_id=1`, `receive_pos_id=1` 하드코딩을 전부 제거하고 실제 board/printer 슬롯 값을 쓰도록 고쳤다. 리베이스 중 `main`으로 덮어써서 깨져 있던 `RobotTaskRepository.get_active_load_for_order_locked` → `get_active_task_for_order_locked` 이름 불일치도 같이 고쳤다.
2. **로봇 점유(mutex) + 순서 보장 추가**: 로봇이 하나뿐인데 LOAD1~LOAD2, UNLOAD1~UNLOAD2 진행 중에 다른 작업이 끼어들 수 있던 구조적 공백을 발견해서 고쳤다.
   - `WorkRequestService._try_dispatch_load1`에 `get_active_real_robot_task_locked` 기반 busy-check 추가.
   - UNLOAD 쪽에도 `RobotTask.dispatch_unload_request`(기존에 정의만 돼 있고 호출되는 곳이 없던 dead code)를 실제로 연결해, UNLOAD 진행 중에도 로봇 점유 상태가 `robot_tasks`에 남게 했다.
   - `timer_service.py`의 타이머 스윕이 프린터 여러 대가 동시에 끝나도 unload1을 한 번에 하나씩만 보내도록(`dispatch_pending_robot_work`) 바꿨다 — 전에는 전부 즉시 발행해서 로봇이 완성품을 든 채로 다음 집기를 요청받는 위험이 있었다.
   - 빈 프린터가 하나도 없으면 load1 자체를 보류하도록 가드 추가 — 안 그러면 로봇이 베드를 집고도 놓을 곳이 없어 영구적으로 멈추는 deadlock이 될 수 있었다.
   - `_try_dispatch_load1`에 "나보다 먼저 기다린 WAITING 주문이 있으면 새치기하지 않는다" 체크 추가, `BoardStockService.refill_complete`가 채우기 완료 즉시 `dispatch_pending_robot_work`를 호출하도록 고쳐서 순서 보장 + 즉시 재시도를 둘 다 만족시켰다.
3. **적재대 비었을 때 주문 자체를 안 만들도록 설계 변경**: 전에는 베드가 없어도 주문을 WAITING으로 저장했는데, 요청에 따라 베드 확인(`_ensure_board_available`)을 주문 생성보다 먼저 하도록 바꿔서 베드 없는 동안 들어온 요청은 주문/robot_tasks를 전혀 남기지 않고 바로 거부하게 했다. `BoardEmptyError`에서 `order_id` 제거(더 이상 주문이 없을 때 발생하는 에러라서), API 응답에서도 제거(프론트가 그 필드를 안 써서 영향 없음 확인).
4. **수동 테스트 현황 문서** [`test-plan-work-request-sqs.md`](test-plan-work-request-sqs.md) 신설: 적재대/작업대/수령대 상황별 37개 테스트케이스를 표로 정리하고, 실제 로컬 서버에 대고 하나씩 확인한 기록을 상태/확인일/비고로 남겼다.

### 알려진 문제 / 참고

- ROS2 쪽 자동 응답기가 모든 명령에 즉시 성공으로만 답해서, **"실패" 시나리오(집기 실패, SQS 발행 실패 등)와 동시성/타이밍이 필요한 테스트는 라이브로 재현이 안 된다** — 이런 건 `pytest`로만 검증했다 (문서의 비고란에 어떤 테스트 함수로 확인했는지 적어둠).
- 이 자동 응답기가 정확히 뭔지(진짜 ROS2 브릿지인지, 별도 스텁/시뮬레이터인지)는 확인하지 않았다 — 다음에 실제 로봇 연동을 테스트할 때는 이게 꺼져 있는지 먼저 확인해야 한다.

### 다음 작업 (우선순위 순)

1. 위 백엔드 변경사항 + `test-plan-work-request-sqs.md` 37개 완료 리뷰 후 커밋 (사용자가 직접 커밋).
2. 여유 있으면: 위에서 발견한 ROS2 쪽 자동 응답기가 뭔지 확인 — 실제 연동 테스트 전에 꺼야 할 수도 있음.

---

## 2026-11-18 — M0609 3D 뷰어를 home으로 이동 + atomic design 재배치

### 현재 상태 (이어서 작업하기 전에 확인)

| 항목 | 상태 |
| --- | --- |
| 커밋 | **커밋 전.** 브랜치 `feat/add_3d_module`, 마지막 커밋 `95549fc feat: add 3d module`. 이 날짜의 변경은 전부 작업 트리에만 있다 |
| 프론트 | `cd app/frontend && npx tsc --noEmit && npm run build` → 통과 |
| 백엔드 | 건드리지 않음 |
| 실제 기동 확인 | `npm run dev`로 홈(`#/`) 접근은 확인(HTML 정상 응답). **브라우저로 3D 뷰어가 실제로 뜨는 화면은 못 봤다** — 아래 "알려진 문제" 때문에 ERROR 배지만 뜰 것 |

### 한 일

#### 1. `DoosanM0609Viewer`를 organisms로 재배치

- `app/frontend/src/components/templates/{react.tsx,index.ts,element.ts,core/,transports/}`는 실제로는 상태를 가진 완결된 컴포넌트(Three.js 씬, URDF 로딩, 조인트 보간 등)인데 `templates/`(레이아웃 전용이어야 함)에 잘못 들어가 있었다. atomic design 규칙 위반.
- `app/frontend/src/components/organisms/DoosanArmViewer/`로 통째로 이동했다. 이 폴더(`core/`, `transports/` 빈 디렉터리)는 이전에 누군가 미리 만들어두고 채우지 않은 상태였다 — 원래 의도된 위치였던 것으로 보인다.
- export 이름(`DoosanM0609Viewer`)과 내부 상대 경로는 그대로 유지했다 (기계적 이동).

#### 2. 홈(대시보드)에 연결

- `DashboardTemplate.tsx`에 `armViewer` 슬롯 추가.
- `DashboardPage.tsx`에서 `<DoosanM0609Viewer assetsBaseUrl="/assets/doosan/m0609_rg2" gripper="rg2" .../>`를 렌더링. `useLiveState().teachingPendant.currentPose`가 JOINT 공간일 때 `posj`(deg)를 `joints` prop으로 그대로 흘려서, 티칭 팬던트로 조그 중인 실제 관절각이 홈 화면 3D 뷰어에도 반영되게 했다 (POSX/TASK 공간일 때는 넘기지 않음 — joint 입력이 아니므로).
- `styles.css`에 `.arm-viewer-panel` 추가 (기존 `.layout` 그리드는 고정 높이가 없어서 뷰어에 명시적 높이 필요).

#### 3. 사전에 있던 버그 2건 수정 (내 변경과 무관하게 `95549fc`에 이미 있던 문제)

| 버그 | 원인 | 수정 |
| --- | --- | --- |
| `npm install`하면 3D 뷰어가 깨짐 | `three`·`urdf-loader`가 `node_modules`엔 물리적으로 있지만 `package.json`/lock에 선언이 안 돼 있었음 (아마 `--save` 없이 수동 설치) | `npm install --save three@0.187.0 urdf-loader@0.13.1` + `npm install --save-dev @types/three`로 정식 선언 |
| 메시 로딩 시 런타임 에러 날 수밖에 없는 구조 | `robot_rig.ts`의 `loader.loadMeshCb`가 3개 인자(`path, manager, done`)로 작성됐는데, 실제 설치된 `urdf-loader@0.13.1` API는 4개 인자(`path, manager, material, done`) | 실제 시그니처로 수정, STL 메시에는 URDF `<material>` 태그에서 온 `material`을 그대로 적용 (하드코딩된 머티리얼 대신) |

- 이 두 버그는 지금까지 `tsc --noEmit`이 이 파일에 대해 성공적으로 돌아간 적이 없었다는 뜻이다 (package.json에 의존성이 없어서 빌드가 애초에 안 됐을 것).

#### 4. `scripts/setup.sh`

- `npm install` 뒤에 `public/assets/doosan/m0609_rg2/`에 `.urdf` 파일이 하나도 없으면 경고를 띄우는 체크 추가 (아래 알려진 문제와 연결).

### 알려진 문제 (미해결)

- **⚠️ 두산 M0609 URDF/메시 파일이 실제로 하나도 없다.** `app/frontend/public/assets/doosan/m0609_rg2/`와 하위 `meshes/`는 git 추적 여부와 상관없이 완전히 빈 디렉터리다. 지금 홈 화면 3D 뷰어는 로드를 시도하다 실패해서 "ERROR" 배지만 표시된다 (컴포넌트 자체는 try/catch로 안전하게 처리되어 있어 화면이 깨지지는 않음). **누군가 실제 URDF + 메시 파일을 이 경로에 넣어야 뷰어가 실제로 로봇을 그린다.**

### 다음 작업 (우선순위 순)

1. **URDF/메시 파일 확보해서 `public/assets/doosan/m0609_rg2/`에 추가.** 이게 없으면 이번 작업 전체가 화면상으로는 "ERROR" 배지 외엔 아무 의미가 없다.
2. 파일을 넣은 뒤 브라우저로 실제 렌더링 확인 (지금까지 한 번도 확인 못 함).
3. 확인되면 기능별로 나눠 커밋 (이번엔 사용자 요청으로 이 세션에서 커밋함 — 평소엔 사용자가 직접 커밋).
4. `teachingPendant` 세션이 비활성(홈에 아무도 조그 안 하는 상태)일 때 3D 뷰어 기본 포즈를 어떻게 할지 정하기 (지금은 `joints`가 `undefined`면 뷰어 내부 기본값 그대로 — 확인 필요).

### 변경 파일 요약

- **이동한 파일 (내용은 거의 그대로):**
  - `app/frontend/src/components/templates/{react.tsx→organisms/DoosanArmViewer/DoosanArmViewer.tsx, index.ts, element.ts, core/*, transports/*}`
- **수정한 파일:**
  - `app/frontend/src/components/organisms/DoosanArmViewer/core/robot_rig.ts` (loadMeshCb 시그니처 버그 수정)
  - `app/frontend/src/components/templates/DashboardTemplate.tsx`, `app/frontend/src/pages/DashboardPage.tsx`, `app/frontend/src/styles.css`
  - `app/frontend/package.json`, `package-lock.json` (three/urdf-loader/@types/three 정식 선언)
  - `app/scripts/setup.sh` (URDF 자산 누락 경고)
- **새로 만든 문서:** 이 항목

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
