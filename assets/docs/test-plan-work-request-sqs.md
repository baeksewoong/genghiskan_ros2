# 테스트 현황 — 작업요청(SQS) 로직

작성일: 2026-11-19 · 작성자: 류병옥 (Claude 보조 작성)

관련 문서: [`prd-work-request-sqs.md`](prd-work-request-sqs.md)

`app/backend/tests/test_work_request.py`, `test_timer_service.py`, `test_teaching_pendant.py`의 적재대/작업대/수령대 관련 테스트를 번호로 묶어 추적한다. `pytest` 자동 테스트는 이미 전부 통과 상태이고, 이 문서는 **실제 로컬 서버(uvicorn + MySQL)에 대고 수동으로 재현해본 기록**을 남기는 용도다.

**상태 값**: ⬜ 대기 · ✅ 완료(정상 동작 확인) · ❌ 실패(버그 발견, 아래 "비고"에 기록) · 🔄 재확인 필요(코드 변경으로 결과가 바뀔 수 있음)

테스트할 때마다 상태/확인일/비고만 고쳐서 커밋하면 된다.

> **2026-11-19 메모:** 로컬 서버에 뭔가가(ROS2 쪽 모킹/스텁으로 보임) 명령 발행 후 150ms 안에 전부 success_*로 자동 응답하고 있다. 그래서 "실패" 시나리오(집기 실패, SQS 발행 실패 등)와 "로봇이 바쁜 중간 상태"처럼 타이밍을 맞춰야 하는 테스트는 라이브로 재현하기 어려워 `pytest`로 대체 검증했다. 단순 happy-path나 상태 없는 체크(존재하지 않는 work_id 등)만 라이브로 직접 확인했다.

---

## 요약

| 구분 | 완료 | 전체 |
| --- | --- | --- |
| A. LOAD 디스패치 | 5 | 5 |
| B. LOAD1→LOAD2 | 4 | 4 |
| C. LOAD 실패/재시도 | 2 | 2 |
| D. 로봇 점유(mutex)·순서보장 | 1 | 1 |
| E. UNLOAD 흐름 | 20 | 20 |
| F. 적재대 리필 | 1 | 1 |
| G. 조그세션 상호배제 | 4 | 4 |
| **전체** | **37** | **37** |

---

## A. 작업요청(LOAD) 디스패치

| 번호 | 적재대 | 작업대 | 수령대 | 테스트 내용 | 예상 결과 | 상태 | 확인일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 전부 EMPTY(베드 없음) | EMPTY | EMPTY | 베드가 하나도 없는 상태에서 작업요청 생성 | BoardEmptyError 발생(409). 주문도 robot_tasks도 생성되지 않음(접수 자체가 거부됨) | ✅ | 2026-11-19 | |
| 2 | 전부 EMPTY → 중간에 채우기 완료로 전부 OCCUPIED | EMPTY | EMPTY | 베드 없는 상태에서 작업요청 2번 반복 시도(둘 다 거부) → 적재대 채우기 완료 → 그 이후에 새 작업요청 생성 | 앞의 2번 시도는 둘 다 거부되고 주문/robot_tasks 전혀 안 남음. 채우기 완료 이후의 요청은 평소처럼 즉시 디스패치됨(DISPATCHING, start_pos_id=3) | ✅ | 2026-11-19 | |
| 3 | 2번 OCCUPIED | 1~3번 전부 PRINTING(꽉 참) | EMPTY | 빈 프린터가 없는 상태에서 작업요청 생성 → 이후 프린터 1번이 비면 재확인 | 처음엔 load1 발행 안 함, 주문 WAITING 유지, 적재대 2번도 예약 안 됨. 프린터 1번이 비면 자동으로 load1(start_pos_id=2) 발행, DISPATCHING 전환 | ✅ | 2026-11-19 | |
| 4 | 2번 OCCUPIED | EMPTY | EMPTY | 정상적으로 작업요청 생성 | 주문 DISPATCHING, 적재대 2번 RESERVED(피킹대기)로 전환. 프린터는 아직 전혀 건드리지 않음 | ✅ | 2026-11-19 | |
| 5 | 2번 OCCUPIED (load1 SQS 발행 실패 상황) | EMPTY | EMPTY | 작업요청 생성 중 SQS 발행 실패 | SqsProduceError 발생. 주문 WAITING으로 남고, 적재대 2번은 RESERVED→OCCUPIED로 원복, robot_tasks도 생성 안 됨 | ✅ | 2026-11-19 | 라이브가 아니라 `pytest tests/test_work_request.py::test_sqs_produce_failure_rolls_back_board_reservation`로 검증 |

## B. LOAD1 성공 → LOAD2(배치) 처리

| 번호 | 적재대 | 작업대 | 수령대 | 테스트 내용 | 예상 결과 | 상태 | 확인일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | 2번에서 디스패치 후 success_load1 수신 | EMPTY | EMPTY | 베드 집기 성공 이벤트 처리 | 주문 LOADING, 적재대 2번 EMPTY. 가장 작은 빈 프린터(1번) RESERVED 배정 + 배치 명령(sd_pos_id=1) 발행. robot_task RUNNING | ✅ | 2026-11-19 | 자동 응답기가 150ms 내로 처리해, 테스트 4·5의 주문(work_id 1,2)에서 `/api/sqs/history`로 자연 발생 확인 |
| 7 | LOAD1·LOAD2 완료 | 1번 배정됨 | EMPTY | 프린터 배치 성공 이벤트 처리 | 주문 PRINTING(started_at 기록), 프린터 1번 PRINTING(타이머 시작). robot_task SUCCEEDED | ✅ | 2026-11-19 | 위와 동일 — `/api/sqs/history`로 확인 |
| 8 | 무관 | 무관 | 무관 | 존재하지 않는 work_id로 success_load2 처리 | 예외 없이 조용히 무시 | ✅ | 2026-11-19 | `pytest::test_place_success_ignores_unknown_work_id` |
| 9 | 무관 | 무관 | 무관 | 존재하지 않는 work_id로 success_load1 처리 | 예외 없이 조용히 무시 | ✅ | 2026-11-19 | `pytest::test_load_success_ignores_unknown_work_id` |

## C. LOAD 실패 / 재시도

| 번호 | 적재대 | 작업대 | 수령대 | 테스트 내용 | 예상 결과 | 상태 | 확인일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 2번 디스패치로 RESERVED | EMPTY | EMPTY | 베드 집기 실패(fail_load1) 이벤트 처리 | 주문/적재대 상태 그대로(DISPATCHING/RESERVED), 알럿만 발생 | ✅ | 2026-11-19 | 자동 응답기가 항상 성공만 보내 라이브 재현 불가 → `pytest::test_load_pick_failed_broadcasts_alert_without_changing_state`로 검증 |
| 11 | 2번 디스패치로 RESERVED | EMPTY | EMPTY | 집기 실패 후 확인 눌러 재시도(retry_load) | 동일한 적재대 슬롯(2)으로 재발행. 첫 발행엔 retry_token 없음, 재시도엔 있음 | ✅ | 2026-11-19 | `pytest::test_retry_load_resends_same_start_pos_id`로 검증 (디스패치가 너무 빨리 끝나 라이브로 그 순간을 못 잡음) |

## D. 로봇 점유(mutex) · 순서 보장

| 번호 | 적재대 | 작업대 | 수령대 | 테스트 내용 | 예상 결과 | 상태 | 확인일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12 | 1·2번 OCCUPIED | EMPTY | EMPTY | 주문A 생성(LOAD1~LOAD2 진행 중)인 상태에서 주문B 생성 | 로봇이 A 작업 중이라 B는 WAITING 유지(적재대 1번 안 건드림) → A가 끝나면 B가 자동 디스패치(start_pos_id=1) | ✅ | 2026-11-19 | `pytest::test_create_defers_load_when_robot_busy_with_another_order`로 검증 (A가 150ms 안에 끝나버려 라이브로 B를 WAITING 상태로 못 붙잡음) |

## E. 출력 완료 → UNLOAD1 → UNLOAD2 → 수령

| 번호 | 적재대 | 작업대 | 수령대 | 테스트 내용 | 예상 결과 | 상태 | 확인일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13 | 무관 | 1번 PRINTING(타이머 만료, 로봇 비어있음) | EMPTY | 타이머 스윕 실행 → 이후 pending-work 재확인 | 스윕 자체는 PRINT_DONE 전환만, unload1은 안 보냄. 재확인 시 프린터 슬롯(1)으로 unload1 발행 | ✅ | 2026-11-19 | 테스트 4의 주문(work_id=2)이 출력 시간(30초) 뒤 자동으로 unload1까지 이어지는 걸 `/api/sqs/history`로 확인 |
| 14 | 무관 | 1·2번 모두 PRINTING(둘 다 타이머 만료) | EMPTY | 두 프린터 동시 만료 → pending-work 반복 확인 → 먼저 처리된 쪽 unload1~unload2 완료 | unload1은 한 번에 하나만 발행. 재확인해도 안 늘어남. 먼저 처리된 게 끝나야 나머지 발행됨 | ✅ | 2026-11-19 | `pytest::test_dispatch_pending_robot_work_serializes_unload1_across_printers`로 검증 (동시성 타이밍이라 라이브로 재현 어려움) |
| 15 | 무관 | 무관(PRINT_DONE 상태) | 1·2 모두 EMPTY | success_unload1 처리 | 주문 UNLOADING, 수령대 1번(기본값)으로 unload2 발행, receive_pos_id=1 | ✅ | 2026-11-19 | work_id 1,2 둘 다 receive_pos_id=1로 배정된 걸 주문 조회로 확인 |
| 16-1 | 무관 | 무관 | 1번 점유·2번 EMPTY | success_unload1 처리 | 2번 배정 | ✅ | 2026-11-19 | `pytest::test_unload1_success_picks_free_receive_pos`(파라미터화) |
| 16-2 | 무관 | 무관 | 1번 배치중·2번 EMPTY | success_unload1 처리 | 2번 배정 | ✅ | 2026-11-19 | 〃 |
| 16-3 | 무관 | 무관 | 2번만 점유·1번 EMPTY | success_unload1 처리 | 1번 배정 | ✅ | 2026-11-19 | 〃 |
| 16-4 | 무관 | 무관 | 1번 이미 수령됨(점유 아님)·2번 EMPTY | success_unload1 처리 | 1번 배정 | ✅ | 2026-11-19 | 〃 |
| 17 | 무관 | 무관 | 1·2번 모두 점유(가득 참) | 수령대 꽉 찬 상태에서 success_unload1 처리 | unload2 미발행(false), "수령대 가득 참" 알럿, 주문 UNLOADING 대기 | ✅ | 2026-11-19 | `pytest::test_unload1_success_does_not_send_when_receive_pos_full`로 검증 |
| 18 | 무관 | 무관 | 1·2 EMPTY (unload2 발행 실패 상황) | success_unload1 처리 중 unload2 발행 실패 | false 반환, 주문 UNLOADING 유지, receive_pos_id 배정 롤백 | ✅ | 2026-11-19 | `pytest::test_unload1_success_keeps_waiting_on_produce_failure`로 검증 |
| 19 | 무관 | 2번 DONE(완성품 있음) | 1·2 EMPTY | success_unload1 처리 | 프린터 2번 DONE→EMPTY로 풀림 | ✅ | 2026-11-19 | work_id 1,2 모두 unload1 이후 프린터 1번이 EMPTY로 풀리는 걸 `/api/state`로 확인 |
| 20 | 무관 | 무관 | 1·2번 모두 점유, 새 주문 unload1 성공으로 대기 중 | 2번 수령대를 수령하기로 비움 | 대기 중이던 주문의 unload2가 2번으로 자동 발행, receive_pos_id=2 | ✅ | 2026-11-19 | `pytest::test_pickup_resumes_waiting_unload2`로 검증 |
| 21 | 무관 | 무관 | 1번 점유(그 주문 자체 수령), 대기 unload2 없음 | 대기 중인 unload2 없는 상태에서 수령하기 | 추가 unload2 발행 없음 | ✅ | 2026-11-19 | work_id 1,2 둘 다 다른 대기 주문 없이 수령 완료, 추가 unload2 로그 없음 확인 |
| 22 | 무관 | 1번에 완성품 있는 PRINT_DONE | 무관 | 집기 실패 후 확인 눌러 unload1 재시도 | 완성품이 놓인 프린터 슬롯(1)으로 재발행, retry_token 포함 | ✅ | 2026-11-19 | `pytest::test_retry_unload1_resends_with_retry_token`로 검증 |
| 23 | 존재하지 않는 주문 | 무관 | 무관 | PRINT_DONE 아닌 주문에 unload1 재시도 요청 | UnloadRetryNotFoundError 발생 | ✅ | 2026-11-19 | `curl -X POST /api/work-requests/999999/retry-unload` → 404 UNLOAD_TASK_NOT_FOUND 직접 확인 |
| 24 | 무관(SQS 로직만 검증) | 무관 | 무관 | 같은 work_id로 최초 발행 + retry_token 재발행 | MessageDeduplicationId가 서로 다름("unload-7" vs "unload-7-abc"), FIFO 큐가 중복으로 안 버림 | ✅ | 2026-11-19 | `pytest::test_retry_dedup_id_differs_from_first_send`로 검증 |
| 25 | 무관 | 무관 | 1번에 unload2 발행됨(RESERVED) | success_unload2 처리 | 주문 READY_FOR_PICKUP 전환(ready_at 기록), receive_pos_id=1 확정 | ✅ | 2026-11-19 | work_id 1,2 둘 다 ready_at 기록 + receive_pos_id=1로 확인 |
| 26 | 무관 | 무관 | 무관(존재하지 않는 work_id) | PRINT_DONE 아닌 주문에 success_unload1 처리 | false 반환, unload2 미발행 | ✅ | 2026-11-19 | `pytest::test_unload1_success_ignores_order_not_print_done`로 검증 |
| 27 | 무관 | 무관(PRINT_DONE 1건) | 무관 | 완성품 집기 실패(fail_unload1) 처리 | 상태 변화 없음(PRINT_DONE 유지), 알럿만 발생 | ✅ | 2026-11-19 | `pytest::test_unload1_failed_broadcasts_alert_without_changing_state`로 검증 |
| 28 | 무관 | 무관 | 1·2 EMPTY → 전 과정 추적 | PRINT_DONE→unload1 성공→unload2 성공→수령하기 전체 실행 | 수령대 1번이 EMPTY→RESERVED→OCCUPIED→EMPTY 순 전이, receive_pos_id=1 이력 남음 | ✅ | 2026-11-19 | work_id 1,2 둘 다 전체 사이클 끝나고 `/api/receive-pos`가 EMPTY로 돌아온 것 확인 |
| 29 | 무관 | 무관 | 1·2 EMPTY(unload2 발행 실패 상황) | success_unload1 처리 중 unload2 발행 실패 | 수령대 1번 배정 안 되고 EMPTY로 남음 | ✅ | 2026-11-19 | `pytest::test_receive_pos_rolls_back_on_produce_failure`로 검증 |

## F. 적재대 리필

| 번호 | 적재대 | 작업대 | 수령대 | 테스트 내용 | 예상 결과 | 상태 | 확인일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 1번 OCCUPIED, 2·3번 EMPTY | 무관 | 무관 | 채우기 완료 처리 | 이미 찬 1번 그대로, 비어있던 2·3번만 OCCUPIED로 전환 | ✅ | 2026-11-19 | `POST /api/board-stock/refill-complete` 호출 결과 1번 `updated_at` 변화 없이 OCCUPIED 유지, 2·3번만 새로 OCCUPIED로 전환됨을 `GET /api/board-stock`으로 확인 |

## G. 조그세션(티칭 팬던트)과의 상호배제

| 번호 | 적재대 | 작업대 | 수령대 | 테스트 내용 | 예상 결과 | 상태 | 확인일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 31 | 2번 디스패치로 LOAD1 진행 중(로봇 점유) | 무관 | 무관 | LOAD1~LOAD2 중 조그 세션 활성화 시도 | RobotBusyError 발생, 세션 비활성 유지 | ✅ | 2026-11-19 | 자동 응답기가 LOAD1~LOAD2를 수백ms 안에 끝내버려 손으로 타이밍을 못 맞춰서, 작업요청 생성 응답을 받는 즉시(지연 없이) 조그 세션 활성화를 쏘는 스크립트로 레이스 — `POST /api/work-requests` 201(DISPATCHING) 받자마자 `POST /api/teaching-pendant/session {"enable":true}` 호출해 409 ROBOT_BUSY 재현. 이후 해당 주문은 방해 없이 LOAD2까지 정상 진행(PRINTING 전환)됨을 `/api/state`로 확인 |
| 32 | 무관 | 1번에 완성품 있는 PRINT_DONE→unload1 디스패치로 로봇 점유 | 무관 | UNLOAD1~UNLOAD2 중 조그 세션 활성화 시도 | RobotBusyError 발생, 세션 비활성 유지 | ✅ | 2026-11-19 | 31번과 같은 이유로 타이밍을 손으로 못 맞춰서, 작업요청 생성 후 `GET /api/orders` 폴링(50ms 간격)으로 PRINT_DONE/UNLOADING 전환을 감지한 즉시 조그 세션 활성화를 쏘는 스크립트로 레이스 — 409 ROBOT_BUSY 재현. 이후 해당 주문은 방해 없이 UNLOAD2까지 정상 진행(READY_FOR_PICKUP 전환)됨을 확인 |
| 33 | 2번 OCCUPIED, 조그 세션 활성 상태 | 무관 | 무관 | 조그 세션 활성 중 작업요청 생성 | LOAD 전혀 발행 안 됨, 주문 WAITING 유지, 적재대 예약 안 건드림 | ✅ | 2026-11-19 | 로봇이 쉬는 동안 조그 세션 활성화 → 작업요청 생성 → 201 WAITING 응답, 적재대(1·2번 OCCUPIED) 그대로. 2초 넘게 더 기다려도 타이머 스윕(`dispatch_pending_robot_work`)이 세션 활성 중엔 재시도조차 안 해 WAITING 유지됨을 확인(`is_session_active()` 체크, [work_request_service.py:585](app/backend/app/services/work_request_service.py#L585)). 세션을 끄자 다음 스윕에서 바로 디스패치되어 PRINTING까지 정상 진행됨 |
| 34 | 2번 OCCUPIED, 조그 세션 활성화 후 비활성화됨 | 무관 | 무관 | 세션 종료 후 작업요청 생성 | 평소처럼 LOAD1 정상 디스패치(DISPATCHING, 적재대 2번 RESERVED) | ✅ | 2026-11-19 | `refill-complete`로 1·2·3번 전부 OCCUPIED → 조그 세션 `{"enable":true}`→`{"enable":false}` → 작업요청 생성 시 201/DISPATCHING, SQS 이력상 start_pos_id=3 LOAD1~LOAD2 정상 완료 확인(슬롯별 단독 OCCUPIED 지정 API가 없어 2번 대신 3번으로 디스패치됐으나 "세션 종료 후 평소처럼 디스패치" 동작 자체는 검증됨) |
