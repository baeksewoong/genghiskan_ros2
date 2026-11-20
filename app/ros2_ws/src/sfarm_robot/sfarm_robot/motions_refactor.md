# motions_refactor.py 설명 (코드 리뷰용)

`motions.py`(2026-11-20 main 기준)를 리뷰하기 쉽게 정리한 사본입니다. 어디서도 import 하지 않고, 실제로 로봇이 쓰는 파일은 그대로 `motions.py`입니다.

## 바꾼 것
1. **함수 위치 재배치:** 기능별로 PART 1~4로 묶었습니다.
2. **주석 정리:** 내 작업 부분(PART 1, 2와 설정값)의 docstring 32개, 주석 14곳을 한두 줄로 줄였습니다. 코드와 안 맞던 설명(무게 판정, 반력 ≥ 등)도 고쳤습니다.
3. **안 쓰는 상수와 꺼 둔 기능 삭제** (1692 → 1310줄)

| 지운 것 | 이유 |
|---|---|
| `WEIGHT_THRESHOLD_N`, `BED_LENGTH_MM` | 안 씀 (예전 무게 판정, 참고용) |
| 좌우 흔들기: `WIGGLE_*` 9개, `_wiggle_side`, `insert_sd`의 흔들기 단계 | `WIGGLE_ENABLE = False` |
| 언로드 정렬 넣기: `_uses_align`, `go_sd_align`, `sd_align_in`, `insert_sd` / `_insert_pre` / `_insert_line`의 정렬 분기 | `SD_ALIGN_INSERT_LAYERS = ()` |
| 실측 정렬 자세: `_align_target`, `_align_shape`, `_push_start`, `_pre_push_points`, `ALIGN_JOINT_TOL_DEG`, `ALIGN_VELJ` | `SD_INSERT_ALIGN_X`, `SD_INSERT_PRE_PUSH_STEPS` 비어 있음 |
| 반력만으로 넣기: `_push_only`와 관련 분기 | 1층만 해당하는데 1층은 `SD_INSERT_CHECK_ONLY`가 먼저라 안 탐 |
| `SD_INSERT_FWD_MM` 분기 | 비어 있음 |
| 적재대 안전 확인 잔여: `_rack_already_exited`, `rack_exit_end_xyz`, `_rack_exit_end`, `RACK_EXIT_KEEP_MM` | 2026-11-19에 안전 확인을 빼서 아무도 안 부름 |
| `_along`, `rotate_about_base_y` | 어디서도 안 부름 |

남긴 것:
- 효과 없는 인자 `go_sd(force)`, `insert_sd(keep_ori)`는 부르는 쪽과 맞추려고 그대로 뒀습니다.
- motion_test 시험 명령이 쓰는 함수(`move_tool_z`, `tilt_ry`, `align_push_axis`, `read_fz`)도 남겼습니다.
- 다른 사람 작업(PART 3 Unload, PART 4 조그/그리퍼, 조그 검증 메모, 언로드 상수)은 주석도 코드도 그대로 뒀습니다.

## 같은지 확인한 방법
| 확인 | 결과 |
|---|---|
| 가짜 로봇으로 원본과 이 파일을 같은 상황에서 돌려, 로봇 명령(movel/movej/그리퍼/순응 제어 등의 순서와 값)과 결과 비교 | 46개 상황 모두 같음 |
| 상황: load1 1~3층 판재 있음/없음, load2 1~3층과 inpush 2층을 반력이 생기는 위치 8가지로 (일찍 걸림 / 완료 / 끝까지 완료 안 됨) | |
| 정의 안 된 이름 검사 | 없음 |

로그 문장은 일부 다릅니다. 예를 들어 "좌우 흔들기 안 함" 줄이 없어졌습니다.

## 누가 만든 부분인지
| 구역 | 담당 |
|---|---|
| PART 1 공통, PART 2 Load | 내 작업 |
| 1-2 `get_current_poses` | ※ 다른 사람 작업 (티칭 팬던트) |
| PART 3 Unload | ※ 다른 사람 작업 |
| PART 4 조그 / 그리퍼 (`run_jog`, `run_gripper`) | ※ 다른 사람 작업 (티칭 팬던트) |

## 파일 구성
```
설정값 (속도, 판재 확인, 넣기, 언로드 상수)        ← 원본 순서 그대로 (지운 상수만 빠짐)
PART 1. 공통
  1-1 홈, 그리퍼, 힘 읽기       go_home, grip_close/open, read_fz, read_force_xyz
  1-2 지금 위치 읽기 (※)        get_current_poses
  1-3 이동 도우미               MotionStopped, _movel_checked, _movel_slow, _move_to
  1-4 자세 계산 / 상대 이동     _zyz_to_mat, rotate_about_base, move_rel, tilt_base, _tool_z_dir, move_tool_z …
PART 2. Load
  2-1 액션 진입점               run_load1, run_load, run_load2
  2-2 Load1                    _load1_common, home_to_board, grip_and_check, put_back_and_home, pull_out, rise_to_top
  2-3 Load2 (1) 적재대 빼기     rack_layer_now, exit_rack
  2-4 Load2 (2) sd 이동         _check_sd_layer, go_sd
  2-5 Load2 (3) 넣기            insert_sd, approach_sd, _check_force_and_release, _insert_line …
  2-6 Load2 (4) 빼기            retreat_sd, _quick_retreat
PART 3. Unload (※)              run_unload1/2, run_unload, unload_move_*, unload_grab_pull
PART 4. 조그 / 그리퍼 (※)       JogRejected, run_jog, run_gripper
```

## Load 흐름

### Load1: 적재대에서 잡고 판재 확인
```
run_load1 / run_load → _load1_common
  home_to_board(층)        홈 → 준비 → 진입 높이 → 잡는 곳
  grip_and_check(층)       닫기 → 30mm 들기 → ry로 숙여 누르기 → Fz 판정 → 원래 자세
    판재 있음 → True (들어 올린 채 멈춤, 다음 load2가 여기서 시작)
    판재 없음 → put_back_and_home: 제자리로 내리기 → 열기 → 뒤로 100mm → 홈 → False
```
판재가 아주 가볍고 얇아서 무게로는 구분이 안 됩니다. 그래서 숙여서 판재 끝이 선반을 누를 때 생기는 **숙인 뒤 Fz**로 판정합니다.

| 층 | 숙이는 각도 | 판재 있음 기준 (숙인 뒤 Fz) | 설정 |
|---|---|---|---|
| 1, 3층 | 9° | > -12.4N | `TILT_CHECK_DEG`, `TILT_CHECK_FZ_N` |
| 2층 | 10° | > -11.4N | `poses.TILT_CHECK_DEG_BY_LAYER`, `TILT_CHECK_FZ_BY_LAYER` |

### Load2: 빼기 → sd 넣기 → 빼기 → 홈
```
run_load2(sd층)
  exit_rack          지금 높이로 층을 알아내서 poses.RACK_EXIT_STEPS 순서대로 빼기
  go_sd              작업대 sd 3 위치로 movej (1, 2층도 sd 3에서 시작)
  insert_sd          층별 방식으로 넣기 → 밀기가 끝나면 항상 그리퍼 열기 (결과 = 완료 확인 여부)
  retreat_sd         층별 빼기
  go_home(fast)      빈손 속도로 홈
```

### 넣기 방식 (poses 설정으로 층마다 정해짐)
| 층 | 다가가기 | 넣기 | 완료 기준 | 빼기 |
|---|---|---|---|---|
| 1층 | `SD_INSERT_APPROACH[1]` 15단계 | 마지막 fwd: 30mm 위치 제어 + 20mm 순응 (`SD_INSERT_CHECK_ONLY`) | 반력 > 0N이면 멈춤, 항상 놓기 | 뒤로 150 → 위로 25 → 홈 |
| 2층 | `SD_INSERT_APPROACH[2]` (아래 80 뒤 side -10) | 입구 → 끝 10mm 앞까지 직선 → 순응 밀기 5mm씩 최대 5번 | 끝 근처 그리고 반력 > 0N | 뒤로 150 → 위로 25 → 홈 |
| 3층 | 없음 (첫 점 → 기울인 입구) | 입구 → 끝 직선 → 순응 밀기 최대 5번 | 끝 근처 그리고 반력 > 1.0N | 넣은 직선 따라 입구까지 → 홈 |

- 1층은 `SD_INSERT_KEEP_Z`로 Z 강성을 높여 높이를 유지한 채 수평으로 밉니다.
- 밀기 끝에 `[넣기] 힘 요약: 최대 반력 …N (…mm에서), 마지막 힘 변화 …` 줄이 나옵니다.
- `insert_sd(..., from_entrance=True)`는 motion_test `inpush` 전용입니다. `enter`로 입구에 와 있을 때 다가가기를 건너뜁니다 (1층은 안 됨).

### 속도
| 상황 | 값 |
|---|---|
| 빈손 (홈 복귀 등) | movej 100, movel 100 |
| 판재 들고 | movej 60, movel 60 |
| 프린터 안 (넣기, 직선) | 30 |
| 순응 밀기 | 10 |
| 놓은 뒤 빼기 (1, 2층) | 60 |
| 회전 단계 | 5°/s, 회전 뒤 0.5초 멈춤 |

## 연결해서 쓰려면 (지금은 연결 안 함)
액션 서버가 쓰는 동작은 `motions.py`와 같아서, 이 파일을 `motions.py`로 덮어쓰면 액션은 그대로 동작합니다.
- motion_test의 `wtest`(`WEIGHT_THRESHOLD_N`), `sda`(`go_sd_align`), `sdain`(`sd_align_in`)은 지운 것을 써서 안 됩니다. 나머지 명령은 됩니다.
- 실제로 바꿔 끼우면, 처음 한 번은 실제 로봇에서 1~3층 load1/load2를 확인해 주세요.
- 이후 `motions.py`가 바뀌면 이 사본은 다시 만들어야 합니다.
