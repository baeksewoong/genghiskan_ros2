# motions.py 설명

로봇 구체 동작 코드입니다. 액션 서버(`robot_action_server.py`)가 `run_load1 / run_load / run_load2 / run_unload1 / run_unload2 / run_unload / run_jog / run_gripper / get_current_poses`를 import 해서 씁니다. 좌표와 층별 설정은 `poses.py`, 언로드 좌표는 `unload_poses.py`에 있습니다.

2026-11-20에 리팩토링한 버전으로 바꿨습니다 (이전 버전은 git 기록 `565c277`, PR #49). 아래 1~3은 그때 바뀐 내용 기록입니다.

| | 이전 | 지금 |
|---|---|---|
| 줄 수 | 1649 | 1133 |
| 구조 | 기능이 섞여 있음 | PART 1 공통 → PART 2 Load(작업 순서) → PART 3 Unload → PART 4 조그/그리퍼 |
| 액션이 쓰는 함수 9개 | | 이름, 인자, 동작 모두 같음 |
| 다른 사람 작업 (PART 3, 4, `get_current_poses`) | | 코드, 주석 그대로 |

## 1. 뺀 것

### 시험용 (motion_test에서만 쓰던 것)
| 지운 것 | 쓰던 motion_test 명령 |
|---|---|
| `tilt_ry` | `ry`, `tilttest` |
| `move_tool_z` | `fwd`, `bwd` |
| `align_push_axis`, `ALIGN_VECT`, `ALIGN_MAX_DEG` (+ import `align_axis`, `DR_AXIS_Z`) | `sd` (sd 뒤 축정렬) |
| `home_to_board`의 `until`, `before_step` 인자, `MotionStopped` | `board`, `board_step` |
| `insert_sd`의 `from_entrance`, `keep_ori` 인자 | `inpush`, `insert` |
| `go_sd`의 `force` 인자 (이미 효과 없었음) | `sd` |

### 꺼 둔 기능 (지금 poses 설정으로는 안 타는 분기)
| 지운 것 | 꺼져 있던 이유 |
|---|---|
| 좌우 흔들며 넣기: `WIGGLE_*` 9개, `_wiggle_side` | `WIGGLE_ENABLE = False` |
| 수평 정렬 넣기: `go_sd_align`, `sd_align_in`, `_uses_align`, 관련 분기 | `SD_ALIGN_INSERT_LAYERS = ()` |
| 실측 정렬 자세: `_align_target`, `_align_shape`, `_pre_push_points`, `_push_start`, `ALIGN_JOINT_TOL_DEG`, `ALIGN_VELJ` | `SD_INSERT_ALIGN_X` 비어 있음 |
| 끝 좌표 없이 밀기: `_push_only`와 분기 | 1층만 해당인데 1층은 `SD_INSERT_CHECK_ONLY`가 먼저 |
| `SD_INSERT_FWD_MM`, `SD_PUSH_START_BEFORE_MM` 분기 | 비어 있음 |
| 넣은 길 전체 거꾸로 빼기 (`retreat_sd` 옛 경로), `load2` 끝 sd 복귀 분기 | 1~3층 모두 `SD_RETREAT_STEPS`가 있어 안 탐 |
| 적재대 빼기 끝 위치 기억: `_rack_exit_end`, `rack_exit_end_xyz`, `_rack_already_exited`, `RACK_EXIT_KEEP_MM` | 2026-11-19 적재대 안전 확인을 빼서 아무도 안 씀 |
| `WEIGHT_THRESHOLD_N`, `BED_LENGTH_MM`, `_along`, `rotate_about_base_y` | 안 씀 (`WEIGHT_THRESHOLD_N`은 motion_test `wtest` 로그에서만 씀) |

### poses.py에서 같이 지운 것
| 지운 것 | 이유 |
|---|---|
| 7번 "시험용 / 꺼진 기능" 칸 전체: `SD_INSERT_FWD_MM`, `SD_INSERT_PUSH_MM`, `SD_PUSH_START_BEFORE_MM`, `SD_INSERT_ALIGN_X/J/BACK_MM`, `SD_INSERT_PRE_PUSH_STEPS`, `SD_ALIGN_INSERT_LAYERS`, `SD_ALIGN_J/X/DEPTH_X` | 위 꺼 둔 기능에서만 읽음 |
| `START_POS_READY_X`, `SD_PRE_INSERT_J`, `SD_INSERT_FRONT_J`, `SD_INSERT_DONE_J` | 어디서도 안 읽음 (실측값은 git 기록에 남아 있음) |

- 이전 `motions.py`도 이 값들을 `getattr(..., 기본값)`으로 읽거나 꺼진 분기에서만 읽어서, **정리한 poses로도 원본 액션 동작이 같습니다** (가짜 로봇 48개 상황, 정리 전/후 로봇 명령 같음).

### 남긴 것
- `read_fz`: `unload.py`(다른 사람 시험 도구)가 써서 남겼습니다. `read_force_xyz()[2]` 한 줄로 줄였고 결과는 같습니다.
- `USE_MOVEL` 전환(movel ↔ movej): 문제 생길 때 되돌리는 스위치라 남겼습니다.
- `go_sd`에서 다가가기 없는 층을 movel로 내리는 분기, `load2`의 "넣기 좌표 없음 → 작업대 앞에서 멈춤": 층 설정이 바뀌어도 안전하게 남겼습니다.

## 2. 정리한 것 (동작은 같음)
| 새 도우미 | 하는 일 | 대신한 곳 |
|---|---|---|
| `_go` | movel + 도착 확인 (못 가면 예외, `check=False`면 경고만) | `_movel_checked`, `_movel_slow`, `move_rel`, `tilt_base`에 4번 반복되던 코드 |
| `_movej` | 빈손/기본 속도 movej | `go_home`, `go_ready`, `_move_to` (3번 반복) |
| `_compliance` (with 문) | 순응 강성 계산 → 켜기 → 끝나면(예외여도) 해제 | 1층 `_check_force_and_release`, 2·3층 `insert_sd`의 try/finally |
| `_need` | 층 좌표가 표에 있는지 확인 (움직이기 전 예외) | `home_to_board`, `_check_sd_layer`, `_insert_line` |
| `_dist` | 두 점 거리 | `_point_on_line`, `_insert_line`, `_check_force_and_release` |
| `_rel_step` | 순서 표 한 단계 실행 (`x/y/z` 직선, `rx/ry/rz` 회전) | `exit_rack`, `retreat_sd` (옛 `_quick_retreat`) |
| `_grip` | 그리퍼 출력 (`grip_close`, `grip_open`은 그대로 있음) | 열기/닫기 같은 코드 |
| `_react`, `_react_n`, `_cur_x`, `_r` | 반력, 층별 반력 기준, 지금 위치, 로그 반올림 | 여러 곳 |

- `home_to_board`는 단계 목록과 람다 대신 순서대로 함수를 부릅니다.
- `_check_force_and_release`의 직선 보간은 `_point_on_line`을 같이 씁니다.
- 주석과 docstring은 한두 줄로 줄였습니다. 날짜, 실측 경위는 `poses.py`에 있어서 뺐습니다.
- 로그 문장은 일부 다릅니다. "좌우 흔들기 안 함" 줄이 없어졌고, 강성 로그가 한 줄로 합쳐졌고, 도착 실패 메시지는 `…까지 못 감 (차이, 목표, 지금, NOT REACHABLE?)` 한 형식으로 통일했습니다.

## 3. 같은지 확인한 방법
| 확인 | 결과 |
|---|---|
| 가짜 로봇으로 이전 버전과 지금 버전을 같은 상황에서 돌려 로봇 명령(movel/movej/movesj/그리퍼/순응 제어/힘 읽기의 순서와 값)과 결과를 비교 | **48개 상황 모두 같음** |
| └ load1 1~3층 × 판재 있음/없음 | 6 |
| └ load2 1~3층 × 반력이 생기는 위치 8가지 (일찍 걸림 / 완료 / 끝까지 완료 안 됨) | 24 |
| └ unload1 → unload2 (층 × 수령대 × 턱 걸림/안 걸림), 조그 3가지(상한 초과 포함), 그리퍼 3가지 | 18 |
| pyflakes (문법, 정의 안 된 이름, 안 쓰는 import) | 통과 |
| import 하는 DSR 이름 16개가 설치된 `DSR_ROBOT2.py`에 있는지 | 모두 있음 |
| 실제 로봇 | **아직 안 함** |

## 4. 누가 만든 부분인지
| 구역 | 담당 |
|---|---|
| 설정값(Load), PART 1 공통, PART 2 Load | 내 작업 |
| 1-2 `get_current_poses` | ※ 다른 사람 작업 (티칭 팬던트) |
| 언로드 상수, PART 3 Unload | ※ 다른 사람 작업 |
| PART 4 조그 / 그리퍼 (`run_jog`, `run_gripper`, 조그 상수) | ※ 다른 사람 작업 (티칭 팬던트) |

## 5. 파일 구성
```
설정값          속도 / 힘 측정 / Load1 판재 확인 / 적재대 빼기 / 넣기 / Unload(※)
PART 1. 공통
  1-1 홈, 그리퍼, 힘     go_home, _grip, grip_close, grip_open, read_force_xyz, read_fz
  1-2 지금 위치 (※)      get_current_poses
  1-3 이동 도우미        _cur_x, _r, _dist, _need, _movej, _go, _movel_checked, _movel_slow, _move_to,
                        move_rel, tilt_base, _rel_step
  1-4 자세 계산          _zyz_to_mat, _mat_to_zyz, rotate_about_base, _tool_z_dir, _point_on_line
PART 2. Load
  2-1 액션 진입점        run_load1, run_load, run_load2
  2-2 Load1             _load1_common, home_to_board, go_ready, go_entry_top, grip_and_check, put_back_and_home
  2-3 Load2 ① 적재대 빼기 rack_layer_now, exit_rack, pull_out, rise_to_top
  2-4 Load2 ② sd 이동    _check_sd_layer, go_sd
  2-5 Load2 ③ 넣기       insert_sd, _check_force_and_release, approach_sd, _approach_points,
                        _insert_pre, _insert_line, _insert_move, _keep_z, _push_dir, _react*, _compliance
  2-6 Load2 ④ 빼기       retreat_sd
PART 3. Unload (※)      run_unload1, run_unload2, run_unload, unload_move_*, unload_return_*,
                        unload_recv_wiggle, unload_*_layer, unload_retreat_home, unload_grab_pull
PART 4. 조그/그리퍼 (※)  JogRejected, run_jog, run_gripper
```

## 6. Load 흐름

### Load1: 적재대에서 잡고 판재 확인
```
run_load1 / run_load → _load1_common
  home_to_board(층)     홈(열기) → 준비 → 진입 높이 → 진입 전 → 잡는 곳   (잡는 곳 전까지 빈손 속도)
  grip_and_check(층)    닫기 → 30mm 들기 → ry로 숙여 Fz → 원래 자세
    판재 있음 → True  (든 채로 멈춤, 다음 load2가 여기서 시작)
    판재 없음 → put_back_and_home: 제자리에 내리기 → 열기 → 뒤로 100mm → 홈 → False
```
| 층 | 숙이는 각도 | 판재 있음 기준 (숙인 뒤 Fz) | 설정 |
|---|---|---|---|
| 1, 3층 | 9° | > -12.4N | `TILT_CHECK_DEG`, `TILT_CHECK_FZ_N` |
| 2층 | 10° | > -11.4N | `poses.TILT_CHECK_DEG_BY_LAYER`, `TILT_CHECK_FZ_BY_LAYER` |

### Load2: 빼기 → sd 이동 → 넣기 → 빼기 → 홈
```
run_load2(sd층)
  exit_rack     지금 높이로 층 판단 → RACK_EXIT_STEPS 순서 (3층은 -X 230 → 3층 높이)
  go_sd         sd 3으로 movej (1, 2층은 여기서 멈추고 insert가 sd 3부터 다가감)
  insert_sd     층별 방식으로 넣기 → 밀기 끝나면 항상 그리퍼 열기 (결과 = 완료 확인 여부)
  retreat_sd    SD_RETREAT_STEPS 순서로 빼기
  go_home       빈손 속도
```

| 층 | 다가가기 | 넣기 | 완료 기준 | 빼기 |
|---|---|---|---|---|
| 1층 | `SD_INSERT_APPROACH[1]` 15단계 | 마지막 fwd 50: 30mm 위치 제어 + 20mm 순응 5mm씩 (높이 고정) | 반력 > 0N이면 멈춤, 항상 놓기 (True) | 뒤로 150 → 위로 25 |
| 2층 | `SD_INSERT_APPROACH[2]` (아래 80 뒤 side -10) | 입구 → 끝 10mm 앞 직선 → 순응 5mm씩 최대 5번 | 끝 근처 그리고 반력 > 0N | 뒤로 150 → 위로 25 |
| 3층 | 첫 점(3초 멈춤) → 기울인 입구 | 입구 → 끝 10mm 앞 직선 → 순응 5mm씩 최대 5번 | 끝 근처 그리고 반력 > 1.0N | 넣은 직선 따라 입구까지 |

밀기 끝에 `[넣기] 힘 요약: 최대 반력 …N (…mm에서), 마지막 힘 변화 …` 줄이 나옵니다.

### 속도
| 상황 | 값 |
|---|---|
| 빈손 (홈, 준비, 적재대 다가가기, 홈 복귀) | movej 100, movel 100 |
| 판재 들고 (들기, 적재대 빼기, sd 3 movej) | 60 |
| 프린터 안 (다가가기, 직선 넣기, 입구로 빼기) | 30 |
| 순응 밀기 | 10 |
| 놓은 뒤 x/y/z 빼기 | 60 |
| 회전 단계 | 5°/s, 회전 뒤 0.5초 멈춤 |

## 7. motion_test 바뀐 명령
| 명령 | 지금 |
|---|---|
| `board_step`, `sda`, `sdain`, `fwd`, `bwd`, `inpush` | 뺌 (지운 기능을 쓰던 시험 명령) |
| `board [층]` | 홈 → 적재대 잡는 곳까지 한 번에 (단계별 멈춤 없음) |
| `sd [층]` | 작업대 이동만 (축정렬, force 없음) |
| `insert [층]` | 액션과 같은 넣기 |
| `ry`, `tilttest` | `tilt_base('y', 도)`로 같은 동작 |
| `wtest` | 그대로 (옛 무게 기준값 출력만 뺌) |

- 처음 한 번은 실제 로봇에서 1~3층 load1 → load2, unload1 → unload2를 천천히 지켜보며 확인해 주세요.
