"""
로봇 구체 동작 (Load / Unload / 조그 / 그리퍼). 설명: motions.md

robot_action_server.py가 goal을 받으면 run_*()를 호출한다.
  - True(또는 None) 반환 -> 성공 / False 반환 -> 실패 / 예외 -> 실패 (message에 예외 내용)

구성 (공통 -> 작업 순서)
  PART 1 공통      : 홈, 그리퍼, 힘 읽기, 이동 도우미, 자세 계산
  PART 2 Load      : Load1 (적재대 잡기 + 판재 확인) -> Load2 (빼기 -> 작업대 이동 -> 넣기 -> 빼고 홈)
  PART 3 Unload    : ※ 다른 사람 작업 (코드 그대로)
  PART 4 조그/그리퍼: ※ 다른 사람 작업 (코드 그대로, 티칭 팬던트)

층별 좌표와 동작 순서는 poses.py / unload_poses.py에 있다.
DSR_ROBOT2를 맨 위에서 import 하므로 robot_action_server.py의 DR_init 설정 뒤에 import 해야 한다 (단독 실행 X).
"""
from __future__ import annotations

import math
from contextlib import contextmanager

from DR_common2 import posj, posx
from DSR_ROBOT2 import (
    DR_BASE,
    DR_MV_MOD_REL,
    DR_TOOL,
    OFF,
    ON,
    fkin,
    get_current_posj,
    get_current_posx,
    get_tool_force,
    movej,
    movel,
    movesj,
    release_compliance_ctrl,
    set_digital_output,
    task_compliance_ctrl,
    wait,
)
# DR_MV_MOD_REL / DR_TOOL은 두산 DRL 매뉴얼 기준 이름 (조그 상대 이동). 실제 설치본에서 ImportError가 나면
# DSR_ROBOT2의 실제 심볼명을 확인해 run_jog()와 같이 고칠 것. 정지(stop)는 robot_action_server.py에서 직접 호출.

from sfarm_interfaces.action import (
    Gripper,
    Jog,
    Load,
    Load1,
    Load2,
    Unload,
    Unload1,
    Unload2,
)

from . import poses, unload_poses

# ---------------------------------------------------------------- 속도
VELJ, ACCJ = 30.0, 30.0                    # 기본 movej
VELX, ACCX = 100.0, 100.0                  # 기본 movel
EMPTY_VELJ, EMPTY_ACCJ = 100.0, 100.0      # 빈손 movej (홈, 준비, 홈 복귀)
EMPTY_VELX, EMPTY_ACCX = 100.0, 100.0      # 빈손 movel (적재대 다가가기)
CARRY_VELJ, CARRY_ACCJ = 60.0, 60.0        # 판재 들고 movej (sd 3으로)
CARRY_VELX, CARRY_ACCX = 60.0, 60.0        # 판재 들고 movel (들기, 적재대 빼기)
QUICK_RETREAT_VELX = 60.0                  # 놓은 뒤 x/y/z로 빼기
INSERT_VELX, INSERT_ACCX = 30.0, 30.0      # 프린터 안 (다가가기, 넣기, 입구로 빼기)
STRAIGHT_VELX, STRAIGHT_ACCX = 30.0, 30.0  # 입구 -> 끝 직선 넣기
PUSH_VELX, PUSH_ACCX = 10.0, 10.0          # 순응 제어로 밀기
ROT_VELX_DEG, ROT_ACCX_DEG = 5.0, 5.0      # 다가가기 회전 단계 (도/s)
ROT_WAIT_SEC = 0.5                         # 회전 단계 뒤 멈춤 (s)

# 적재대 진입 전 -> 잡는 곳 이동: True = movel(posx), False = movej(posj, movel 문제 시 되돌리기용)
USE_MOVEL = True
REACH_TOL_MM = 3.0   # movel 도착 확인 허용 오차. 못 가는 좌표면 movel이 에러 없이 넘어가서 직접 확인

# ---------------------------------------------------------------- 힘 측정
FORCE_SAMPLES = 5            # 평균 횟수
FORCE_SAMPLE_INTERVAL = 0.1  # 측정 간격 (s)
SETTLE_SEC = 0.5             # 이동 후 힘 재기 전 대기 (s)

# ---------------------------------------------------------------- Load1: 잡기 / 판재 확인
LIFT_Z_MM = 30.0             # 잡은 뒤 들어 올리는 높이
# 판재 확인: 들어 올린 뒤 ry로 앞쪽을 숙여 판재 끝이 선반을 누르게 -> 숙인 뒤 Fz > 기준이면 판재 있음.
#   층별 값은 poses.TILT_CHECK_*_BY_LAYER (없으면 아래 기본값, 실측: 있음 -11.7~-12.1N / 없음 -12.7~-13.1N)
TILT_CHECK_DEG = 9.0
TILT_CHECK_FZ_N = -12.4
TILT_CHECK_SETTLE_SEC = 1.0
TILT_CHECK_SAMPLES = 10
PUT_BACK_RETREAT_MM = 100.0  # 판재 없음: 내려놓고 그리퍼 연 뒤 -X로 빠지는 거리

# ---------------------------------------------------------------- Load2: 적재대 빼기 (RACK_EXIT_STEPS 없는 층)
PULL_OUT_MM = 230.0          # -X로 빼는 거리 (판재 215mm + 여유)

# ---------------------------------------------------------------- Load2: 작업대 넣기
PRE_INSERT_HOLD_SEC = 3.0    # 첫 점(입구 전)에서 멈춤 (s)
JAM_FORCE_N = 20.0           # 위치 제어로 넣는 중 X/Y 힘 변화가 이 값 넘으면 걸림 -> 멈춤 (잡은 채로)
PUSH_START_BEFORE_MM = 10.0  # 끝 이만큼 앞부터 순응 제어로 밀기
PUSH_OVERSHOOT_MM = 15.0     # 끝보다 이만큼 더까지 목표를 보냄 (층별: poses.SD_PUSH_OVERSHOOT_MM)
PUSH_FORCE_N = 5.0           # 끝 + PUSH_OVERSHOOT_MM에서 이 힘이 되게 X 강성 계산
PUSH_STEP_MM = 5.0           # 순응 밀기 한 번 거리
PUSH_FORCE_SAMPLES = 2
CHECK_STEP_MM = 5.0          # SD_INSERT_CHECK_ONLY 층(1층) 순응 밀기 한 번 거리
DONE_POS_TOL_MM = 2.0        # 진행 >= 끝 - 이 값이면 위치 도착
DONE_REACT_N = 1.0           # 반력 > 이 값이면 힘 맞음 (층별: poses.SD_DONE_REACT_N)
COMPLIANCE_STX = [500, 3000, 3000, 200, 200, 200]   # 순응 강성 (N/m, Nm/rad). X는 PUSH_FORCE_N으로 다시 계산
KEEP_Z_STIFF_N_M = 20000.0   # SD_INSERT_KEEP_Z 층: Z 강성 최대 -> 밀 때 높이 고정

# ---------------------------------------------------------------- Unload (※ 다른 사람 작업)
UNLOAD_VELJ, UNLOAD_ACCJ = 22.5, 22.5
UNLOAD_VELX, UNLOAD_ACCX = 67.5, 67.5
# 수령대에 놓은 뒤 홈 복귀: 경유 좌표 전체를 movesj(관절 스플라인) 한 번으로 멈춤 없이 이동.
#   좌표별 속도(UNLOAD_SLOW_MOVES)는 적용되지 않고 이 속도 하나로 간다 (deg/s, deg/s^2).
UNLOAD_RETURN_VELJ, UNLOAD_RETURN_ACCJ = 27.0, 22.5   # 속도만 올림 (가속도는 기본 언로드와 같게)
# 수령대에서 놓기 전 자리 맞추기: base 좌표 기준 좌우(UNLOAD_WIGGLE_AXIS)로 ±mm 흔든 뒤 중심으로 돌아와 놓는다.
UNLOAD_WIGGLE_AXIS = 'Y'            # 좌우 축 (base 기준 'X' / 'Y'). 실제 방향이 다르면 바꿀 것
UNLOAD_WIGGLE_MM = 2.0              # 한쪽으로 움직이는 거리 (mm)
UNLOAD_WIGGLE_VELX, UNLOAD_WIGGLE_ACCX = 10.0, 10.0   # mm/s, mm/s^2 (짧은 거리라 천천히)
# 잡은 뒤 이동(베드 빼내기 7~11번 / 수령대 / 복귀)을 movel(직선)로 할지. False면 예전처럼 movej.
#   좌표는 posj로 저장돼 있어서 movel 때는 fkin으로 posx로 바꿔서 간다.
UNLOAD_USE_MOVEL = True
UNLOAD_ARRIVE_WAIT_SEC = 1.0        # 언로드 층 도착 후 잡기 전 대기 (s)
UNLOAD_SETTLE_SEC = 1.0             # 그리퍼 닫은 뒤 / 위치 이동 후 힘 측정 전 대기 (s)
UNLOAD_PULL_POS_MM = 160.0          # 위치 제어로 당기는 거리 (-X, mm)
UNLOAD_PULL_COMPLIANCE_MM = 10.0    # 순응 제어로 더 당기는 거리 (mm)
UNLOAD_PULL_VELX, UNLOAD_PULL_ACCX = 30.0, 30.0
UNLOAD_PULL_STEP_MM = 5.0           # 순응 구간에서 끊어 가는 거리 (mm)
UNLOAD_CATCH_FORCE_N = 0.7          # X 방향 힘 변화가 이 값(N) 이상이면 턱에 걸림
UNLOAD_PULL_FORCE_SAMPLES = 3       # 힘 측정 평균 횟수
UNLOAD_PULL_REACH_TOL_MM = 3.0      # 위치 제어 이동 허용 오차 (mm)

_ROT = ('rx', 'ry', 'rz')


# ============================================================================
# PART 1. 공통 - 홈 / 그리퍼 / 힘 읽기 / 이동 도우미 / 자세 계산
# ============================================================================

# ---- 1-1. 홈, 그리퍼, 힘 읽기
def go_home(fast: bool = False) -> None:
    """홈으로 movej. fast=True면 빈손 속도."""
    _movej(poses.HOME_J, fast)


def _grip(close: bool) -> None:
    set_digital_output(1, ON if close else OFF)
    set_digital_output(2, OFF if close else ON)
    wait(1.5)


def grip_close() -> None:
    _grip(True)


def grip_open() -> None:
    _grip(False)


def read_force_xyz(samples: int = FORCE_SAMPLES) -> list:
    """베이스 기준 툴 외력 [Fx, Fy, Fz](N) 평균."""
    total = [0.0, 0.0, 0.0]
    for _ in range(samples):
        f = get_tool_force(DR_BASE)
        total = [total[i] + float(f[i]) for i in range(3)]
        wait(FORCE_SAMPLE_INTERVAL)
    return [v / samples for v in total]


def read_fz() -> float:
    """베이스 기준 Fz(N) 평균 (unload.py에서 사용)."""
    return read_force_xyz()[2]


# ---- 1-2. 지금 위치 읽기 (※ 다른 사람 작업 - 티칭 팬던트용)
def get_current_poses() -> tuple[list[float], list[float]]:
    """현재 로봇의 관절 좌표(posj)와 직교 좌표(posx)를 float[6] 리스트로 반환."""
    cur_j = get_current_posj()
    posj_vals = (
        [float(v) for v in cur_j[:6]]
        if isinstance(cur_j, (list, tuple)) and len(cur_j) >= 6
        else [0.0] * 6
    )

    cur_x_res = get_current_posx()
    cur_x = cur_x_res[0] if isinstance(cur_x_res, tuple) else cur_x_res
    posx_vals = (
        [float(v) for v in cur_x[:6]]
        if isinstance(cur_x, (list, tuple)) and len(cur_x) >= 6
        else [0.0] * 6
    )
    return posj_vals, posx_vals


# ---- 1-3. 이동 도우미 (모든 movel은 도착 확인)
def _cur_x() -> list:
    return list(get_current_posx()[0])


def _r(p, n: int = 1) -> list:
    """로그용 반올림."""
    return [round(v, n) for v in p]


def _dist(a: list, b: list) -> float:
    """두 점의 X/Y/Z 거리 (mm)."""
    return math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))


def _need(layer: int, *tables: tuple[dict, str]) -> None:
    """(표, 이름)마다 layer층 좌표가 있는지 확인. 없으면 움직이기 전에 예외."""
    for table, name in tables:
        if layer not in table:
            raise ValueError(f'{name}에 {layer}층 좌표 없음 (가능: {list(table)})')


def _movej(pose_j: list, fast: bool = False) -> None:
    v, a = (EMPTY_VELJ, EMPTY_ACCJ) if fast else (VELJ, ACCJ)
    movej(posj(*pose_j), vel=v, acc=a)


def _go(target: list, vel, acc, what: str = '목표', check: bool = True, log=print) -> None:
    """movel 후 도착 확인 (못 가는 좌표면 movel이 에러 없이 넘어가서). check=False면 경고만."""
    movel(posx(*target), vel=vel, acc=acc)
    now = _cur_x()
    err = max(abs(now[i] - target[i]) for i in range(3))
    if err <= REACH_TOL_MM:
        return
    msg = f'{what}까지 못 감 (차이 {err:.1f}mm, 목표 {_r(target[:3])}, 지금 {_r(now[:3])}, NOT REACHABLE?)'
    if check:
        raise RuntimeError(msg)
    log(f'  [경고] {msg} -> 그대로 계속')


def _movel_checked(pose_x: list, fast: bool = False, vel: float | None = None) -> None:
    """fast=True면 빈손 속도, vel을 주면 그 속도(acc도 같게), 아니면 기본 속도."""
    v, a = (vel, vel) if vel is not None else (EMPTY_VELX, EMPTY_ACCX) if fast else (VELX, ACCX)
    _go(pose_x, v, a)


def _movel_slow(target: list, name: str, rotate: bool = False) -> None:
    """INSERT_VELX. rotate=True면 회전을 ROT_VELX_DEG로 천천히 하고 ROT_WAIT_SEC 멈춤."""
    if rotate:
        _go(target, [INSERT_VELX, ROT_VELX_DEG], [INSERT_ACCX, ROT_ACCX_DEG], name)
        wait(ROT_WAIT_SEC)
    else:
        _go(target, INSERT_VELX, INSERT_ACCX, name)


def _move_to(pose_j: list | None, pose_x: list, fast: bool = False) -> None:
    """USE_MOVEL이면 movel(posx), 아니면 movej(posj)."""
    if USE_MOVEL:
        _movel_checked(pose_x, fast=fast)
    elif pose_j is None:
        raise ValueError('관절 좌표(J)가 없어 movej로 갈 수 없음 (USE_MOVEL=True로 쓰거나 J 측정)')
    else:
        _movej(pose_j, fast)


def move_rel(dx: float = 0.0, dy: float = 0.0, dz: float = 0.0, log=print, check: bool = True,
             vel: float = INSERT_VELX) -> None:
    """자세 그대로 X/Y/Z mm 직선 이동."""
    cur = _cur_x()
    target = [cur[0] + dx, cur[1] + dy, cur[2] + dz] + cur[3:]
    log(f'  [이동] {_r(cur[:3])} -> {_r(target[:3])} (dX {dx:+.0f} dY {dy:+.0f} dZ {dz:+.0f})')
    _go(target, vel, vel, check=check, log=log)


def tilt_base(axis: str, deg: float, log=print, check: bool = True) -> None:
    """그리퍼 끝 위치 그대로 베이스 axis축으로 deg 회전 (10도/s).

    그리퍼가 +X를 볼 때 rx = 좌우 눕히기, ry = 앞쪽 숙이기(+)/들기, rz = 좌우 돌리기.
    """
    cur = _cur_x()
    target = cur[:3] + rotate_about_base(axis, cur[3:6], deg)
    log(f'  [r{axis} {deg:+.1f}도] 자세 {_r(cur[3:6], 2)} -> {_r(target[3:6], 2)}')
    _go(target, [INSERT_VELX, 10.0], [INSERT_ACCX, 10.0], f'r{axis} 회전', check, log)


def _rel_step(kind: str, val: float, log=print, vel: float = INSERT_VELX, check: bool = True) -> None:
    """순서 표의 한 단계 실행: ('x'/'y'/'z', mm) 직선 / ('rx'/'ry'/'rz', 도) 회전."""
    if kind in ('x', 'y', 'z'):
        d = [0.0, 0.0, 0.0]
        d['xyz'.index(kind)] = val
        move_rel(*d, log=log, check=check, vel=vel)
    elif kind in _ROT:
        tilt_base(kind[1], val, log=log, check=check)
    else:
        raise ValueError(f'단계 종류를 모름: {kind} (x / y / z / rx / ry / rz)')


# ---- 1-4. 자세 계산 (두산 posx 자세 = ZYZ 오일러, 도)
def _zyz_to_mat(a: float, b: float, c: float) -> list:
    a, b, c = (math.radians(v) for v in (a, b, c))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb * cc - sa * sc, -ca * cb * sc - sa * cc, ca * sb],
            [sa * cb * cc + ca * sc, -sa * cb * sc + ca * cc, sa * sb],
            [-sb * cc, sb * sc, cb]]


def _mat_to_zyz(m: list) -> list:
    b = math.atan2(math.hypot(m[0][2], m[1][2]), m[2][2])
    if abs(math.sin(b)) < 1e-9:   # 특이점 (B = 0/180): C = 0
        return [math.degrees(math.atan2(m[1][0], m[0][0])), math.degrees(b), 0.0]
    a = math.atan2(m[1][2], m[0][2])
    c = math.atan2(m[2][1], -m[2][0])
    return [math.degrees(a), math.degrees(b), math.degrees(c)]


def rotate_about_base(axis: str, abc: list, deg: float) -> list:
    """자세 abc를 베이스 axis('x'/'y'/'z')축으로 deg 돌린 자세."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    rot = {'x': [[1, 0, 0], [0, c, -s], [0, s, c]],
           'y': [[c, 0, s], [0, 1, 0], [-s, 0, c]],
           'z': [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    m = _zyz_to_mat(*abc)
    return _mat_to_zyz([[sum(rot[i][k] * m[k][j] for k in range(3)) for j in range(3)] for i in range(3)])


def _tool_z_dir(ori: list) -> list:
    """자세 -> 베이스 기준 툴 Z축(그리퍼가 보는 방향, 미는 축) 단위벡터."""
    a, b = math.radians(ori[0]), math.radians(ori[1])
    return [math.cos(a) * math.sin(b), math.sin(a) * math.sin(b), math.cos(b)]


def _point_on_line(front: list, done: list, d: float) -> list:
    """front -> done 직선에서 d(mm) 간 점. 자세는 비율로 보간 (끝을 넘으면 끝 자세)."""
    t = d / _dist(front, done)
    tt = min(max(t, 0.0), 1.0)
    return [front[i] + (done[i] - front[i]) * t for i in range(3)] + \
        [front[i] + (done[i] - front[i]) * tt for i in range(3, 6)]


# ============================================================================
# PART 2. Load - 적재대에서 판재 꺼내 작업대(sd)에 넣기
# ============================================================================

# ---- 2-1. 액션 진입점
def run_load1(goal: Load1.Goal, log=print) -> bool:
    """Load1: 홈 -> 적재대 start_pos_id층 잡기 -> 판재 확인.

    True: 들어 올린 채로 멈춤 (다음 Load2가 여기서 시작) / False: 판재 내려놓고 홈.
    """
    return _load1_common(goal, 'load1', log=log)


def run_load(goal: Load.Goal, log=print) -> bool:
    """Load: run_load1과 같음."""
    return _load1_common(goal, 'load', log=log)


def run_load2(goal: Load2.Goal, log=print) -> bool:
    """Load2: (Load1로 든 상태) 적재대 빼기 -> 작업대 sd_pos_id층 이동 -> 넣기 -> 빼기 -> 홈.

    반환값은 넣기 완료 확인 여부 (실패해도 그리퍼는 열고 홈으로 간다).
    """
    layer = goal.sd_pos_id
    _check_sd_layer(layer)
    log(f'[load2] 빼기 -> 작업대 {layer}층')
    exit_rack(log=log)
    go_sd(layer, log=log)
    if layer not in poses.SD_INSERT_DONE_X and not _uses_approach(layer):
        log(f'[load2] 작업대 {layer}층 넣기 좌표 없음 -> 작업대 앞에서 멈춤')
        return True
    ok = insert_sd(layer, log=log)
    if not ok:
        log('[load2] 넣기 완료 확인 안 됨 (위치/반력) -> 그래도 그리퍼 열었으니 빼고 홈으로. 결과 False')
    retreat_sd(layer, log=log)
    log('[load2] 홈 이동 (빈손 속도)')
    go_home(fast=True)
    return ok


# ---- 2-2. Load1: 홈 -> 적재대 -> 잡기 -> 판재 확인 -> (없으면) 내려놓고 홈
def _load1_common(goal, name: str, log=print) -> bool:
    layer = goal.start_pos_id
    log(f'[{name}] 적재대 {layer}층')
    home_to_board(layer)
    if grip_and_check(poses.START_POS_PICK_X[layer], log=log, layer=layer):
        return True
    log(f'[{name}] 판재 없음 (숙여 누르기 확인) -> 판재 내려놓고 홈으로 (결과 False)')
    put_back_and_home(layer, log=log)
    return False


def home_to_board(layer: int) -> None:
    """홈(그리퍼 열기) -> 준비 -> 진입 높이 -> 진입 전(Z 하강) -> 적재대 layer층 잡는 곳. 잡는 곳 전까지는 빈손 속도."""
    _need(layer, (poses.START_POS_READY_J, 'START_POS_READY'), (poses.START_POS_APPROACH_X, 'START_POS_APPROACH'),
          (poses.START_POS_PICK_X, 'START_POS_PICK'))
    go_home(fast=True)
    grip_open()
    go_ready(layer, fast=True)
    go_entry_top(layer, fast=True)
    _move_to(poses.START_POS_APPROACH_J.get(layer), poses.START_POS_APPROACH_X[layer], fast=True)
    _move_to(poses.START_POS_PICK_J.get(layer), poses.START_POS_PICK_X[layer])


def go_ready(layer: int, fast: bool = False) -> None:
    """준비 자세로 movej (홈과 손목 자세가 크게 달라 movel이면 특이점을 지남)."""
    _movej(poses.START_POS_READY_J[layer], fast)


def go_entry_top(layer: int, fast: bool = False) -> None:
    """layer층 진입 전 X/Y, 공통 진입 높이(ENTRY_LAYER층 진입 전 Z)로 movel."""
    top = list(poses.START_POS_APPROACH_X[layer])
    top[2] = poses.START_POS_APPROACH_X[poses.ENTRY_LAYER][2]
    _movel_checked(top, fast=fast)


def grip_and_check(pose_x: list, log=print, layer: int | None = None) -> bool:
    """잡기 -> +Z LIFT_Z_MM -> ry로 숙여 Fz 측정 -> 되돌리기. 숙인 뒤 Fz > 기준이면 판재 있음."""
    deg = getattr(poses, 'TILT_CHECK_DEG_BY_LAYER', {}).get(layer, TILT_CHECK_DEG)
    fz_n = getattr(poses, 'TILT_CHECK_FZ_BY_LAYER', {}).get(layer, TILT_CHECK_FZ_N)
    grip_close()
    lifted = list(pose_x)
    lifted[2] += LIFT_Z_MM
    _movel_checked(lifted, vel=CARRY_VELX)
    wait(TILT_CHECK_SETTLE_SEC)
    fz0 = read_force_xyz(TILT_CHECK_SAMPLES)[2]
    tilt_base('y', deg, log=log, check=False)
    wait(TILT_CHECK_SETTLE_SEC)
    fz1 = read_force_xyz(TILT_CHECK_SAMPLES)[2]
    tilt_base('y', -deg, log=log, check=False)
    picked = fz1 > fz_n
    log(f'[판재 확인] {layer if layer is not None else "?"}층 ry +{deg:g}도 숙여 누르기: 전 Fz={fz0:.2f}N  '
        f'숙인 뒤 Fz={fz1:.2f}N (차이 {fz1 - fz0:+.2f}N)  기준: 숙인 뒤 Fz > {fz_n}N  '
        f'-> {"판재 있음" if picked else "판재 없음"}')
    return picked


def put_back_and_home(layer: int, log=print) -> None:
    """판재 없음: 잡는 곳으로 내려 그리퍼 열기 -> -X PUT_BACK_RETREAT_MM -> 홈."""
    log(f'[내려놓기] 적재대 {layer}층: 제자리로 내리기 -> 그리퍼 열기 -> 뒤로 {PUT_BACK_RETREAT_MM:.0f}mm -> 홈')
    pick = list(poses.START_POS_PICK_X[layer])
    _movel_slow(pick, '잡는 곳(내려놓기)')
    grip_open()
    wait(SETTLE_SEC)
    back = list(pick)
    back[0] -= PUT_BACK_RETREAT_MM
    _movel_checked(back)
    go_home(fast=True)
    log('[내려놓기] 홈 도착 (빈손)')


# ---- 2-3. Load2 (1) 적재대에서 빼기
def rack_layer_now() -> int | None:
    """지금 위치가 적재대 몇 층에서 잡고 든 높이인지. 적재대 쪽이 아니거나 높이가 안 맞으면 None."""
    cur = _cur_x()
    picks = poses.START_POS_PICK_X
    if cur[1] <= min(x[1] for x in picks.values()) - 100.0:
        return None
    best = min(picks, key=lambda n: abs(cur[2] - (picks[n][2] + LIFT_Z_MM)))
    if abs(cur[2] - (picks[best][2] + LIFT_Z_MM)) > poses.RACK_LAYER_Z_TOL_MM:
        return None
    return best


def exit_rack(layer: int | None = None, log=print) -> None:
    """적재대에서 판재 빼기. 층은 지금 높이로 판단.

    poses.RACK_EXIT_STEPS에 순서가 있으면 그대로 (도착 오차는 경고만), 없으면 pull_out -> rise_to_top.
    """
    if layer is None:
        layer = rack_layer_now()
        if layer is None:
            raise RuntimeError(f'적재대에서 잡고 든 위치가 아님 (지금 {_r(_cur_x()[:3])}) -> 빼기 안 함. '
                               f'load1 먼저 할 것')
    steps = poses.RACK_EXIT_STEPS.get(layer)
    if not steps:
        log(f'[적재대 빼기] {layer}층: 기본 동작 (-X {PULL_OUT_MM:.0f}mm -> 3층 높이로 올리기)')
        pull_out(log=log)
        rise_to_top(log=log)
        return
    log(f'[적재대 빼기] {layer}층 순서 {len(steps)}단계: {steps}')
    for i, (kind, val) in enumerate(steps, 1):
        log(f' {i}/{len(steps)} {kind} {val:+g}')
        _rel_step(kind, val, log=log, vel=CARRY_VELX, check=False)
    log(f'[적재대 빼기] 끝: {_r(_cur_x())}')


def pull_out(dist: float = PULL_OUT_MM, log=print) -> None:
    """높이/옆/자세 그대로 -X로 dist 빼기 (판재 든 속도)."""
    cur = _cur_x()
    target = list(cur)
    target[0] -= dist
    log(f'[빼기] X {cur[0]:.1f} -> {target[0]:.1f} (-{dist:.0f}mm), Y {cur[1]:.1f}, Z {cur[2]:.1f} 유지')
    _movel_checked(target, vel=CARRY_VELX)


def rise_to_top(log=print) -> None:
    """X/Y/자세 그대로 3층 들어 올린 높이(적재대 3층 Z + LIFT_Z_MM)까지 올리기. 이미 높으면 안 움직임."""
    top_z = poses.START_POS_PICK_X[poses.ENTRY_LAYER][2] + LIFT_Z_MM
    cur = _cur_x()
    if cur[2] >= top_z - REACH_TOL_MM:
        log(f'[올리기] 지금 Z {cur[2]:.1f} >= 3층 높이 {top_z:.1f} -> 안 움직임')
        return
    target = list(cur)
    target[2] = top_z
    log(f'[올리기] Z {cur[2]:.1f} -> {top_z:.1f} (3층 높이, X {cur[0]:.1f} Y {cur[1]:.1f} 그대로)')
    _movel_checked(target, vel=CARRY_VELX)


# ---- 2-4. Load2 (2) 작업대 sd 위치로 이동
def _check_sd_layer(layer: int) -> None:
    _need(layer, (poses.SD_POS_X, 'SD_POS'))


def go_sd(layer: int = 3, log=print) -> None:
    """판재 든 채 sd 3(SD_TOP_LAYER)으로 movej (관절값 확인).

    다가가기 층(1, 2층)은 여기서 멈추고 insert_sd가 sd 3부터 내려간다. 그 외 층은 movel로 그 층 sd까지.
    """
    _check_sd_layer(layer)
    top = poses.SD_TOP_LAYER
    log(f'[작업대] 지금 {_r(_cur_x()[:3])} -> 작업대 {top}층 {poses.SD_POS_X[top][:3]} (movej)')
    movej(posj(*poses.SD_POS_J[top]), vel=CARRY_VELJ, acc=CARRY_ACCJ)
    j = list(get_current_posj())
    if max(abs(j[i] - poses.SD_POS_J[top][i]) for i in range(6)) > 1.0:
        raise RuntimeError(f'작업대 {top}층에 못 감: 목표 J={poses.SD_POS_J[top]} 현재 J={_r(j)}')
    if layer == top:
        return
    if _uses_approach(layer):
        log(f'[작업대] {layer}층은 insert에서 sd 3부터 다가가기 순서로 내려감 -> 여기서 멈춤')
    else:
        log(f'[작업대] {top}층 -> {layer}층 {poses.SD_POS_X[layer][:3]} (movel 하강)')
        _movel_checked(poses.SD_POS_X[layer], vel=CARRY_VELX)


# ---- 2-5. Load2 (3) 넣기
#   1층 (SD_INSERT_CHECK_ONLY): 다가가기 -> 마지막 fwd를 순응 제어로 밀며 반력 확인 -> 항상 놓기 (True)
#   2층 (SD_INSERT_APPROACH)  : 다가가기 끝 = 입구 -> 직선으로 SD_INSERT_DONE_X -> 순응 밀기 (위치 + 반력)
#   3층                       : 첫 점(SD_PRE_INSERT) -> 입구(SD_INSERT_FRONT) -> 끝(SD_INSERT_DONE) 순응 밀기
def insert_sd(layer: int = 3, log=print) -> bool:
    """작업대 layer층에 넣고 놓기. 완료(끝 위치 + 반력) 확인되면 True. 완료 아니어도 그리퍼는 연다."""
    if getattr(poses, 'SD_INSERT_CHECK_ONLY', {}).get(layer):
        return _check_force_and_release(layer, log=log)
    front, done, u, length = _insert_line(layer)
    pre = _insert_pre(layer)
    log(f'[넣기] 첫 점 {_r(pre[:3])} -> 입구 {_r(front[:3])} -> 끝 {_r(done[:3])} '
        f'(직선 {length:.1f}mm, 방향 {_r(u, 3)})')

    # 1) 첫 점 -> 멈춤 -> 입구
    if _uses_approach(layer):
        approach_sd(layer, log=log)
    else:
        _movel_checked(pre, vel=INSERT_VELX)
    log(f'[넣기] {PRE_INSERT_HOLD_SEC}초 멈춤')
    wait(PRE_INSERT_HOLD_SEC)
    log(f'[넣기] 입구 {_r(front[:3])} 자세 {_r(front[3:6], 2)}')
    _movel_checked(front, vel=INSERT_VELX)
    wait(SETTLE_SEC)
    base = read_force_xyz()
    log(f'[넣기] 기준 힘 Fx={base[0]:.1f} Fy={base[1]:.1f} Fz={base[2]:.1f}N')

    # 2) 위치 제어로 끝 PUSH_START_BEFORE_MM 앞까지 (걸리면 멈춤)
    s0 = length - PUSH_START_BEFORE_MM
    _insert_move(_point_on_line(front, done, s0), base, log, '일자로 넣기', vel=STRAIGHT_VELX, acc=STRAIGHT_ACCX)
    s_max = length + getattr(poses, 'SD_PUSH_OVERSHOOT_MM', {}).get(layer, PUSH_OVERSHOOT_MM)

    # 3) 순응 제어로 같은 직선을 PUSH_STEP_MM씩 밀며 끝 위치 + 반력 확인
    wait(SETTLE_SEC)
    base = read_force_xyz()
    react_n = _react_n(layer)
    log(f'[넣기] 순응 제어로 밀기: 직선 {s0:.1f} -> 최대 {s_max:.1f}mm, {PUSH_STEP_MM:.0f}mm씩 '
        f'(완료: 진행 >= {length - DONE_POS_TOL_MM:.1f}mm 그리고 반력 > {react_n}N)')
    finished = False
    max_react, max_at, last_f = -1e9, 0.0, [0.0, 0.0, 0.0]
    with _compliance(layer, log):
        st = s0
        while st < s_max - 1e-9:
            st = min(st + PUSH_STEP_MM, s_max)
            movel(posx(*_point_on_line(front, done, st)), vel=PUSH_VELX, acc=PUSH_ACCX)
            f = read_force_xyz(PUSH_FORCE_SAMPLES)
            cur = _cur_x()
            s_now = sum((cur[i] - front[i]) * u[i] for i in range(3))   # 직선 위 진행 거리
            react = _react(f, base, u)
            last_f = [f[i] - base[i] for i in range(3)]
            if react > max_react:
                max_react, max_at = react, st
            reached = s_now >= length - DONE_POS_TOL_MM
            force_ok = react > react_n
            msg = (f'  [밀기 {st:.1f}mm] 진행 {s_now:.1f}mm (끝까지 {length - s_now:+.1f}mm, 덜 감 {st - s_now:.1f}mm) '
                   f'반력 {react:+.2f}N  Fx={f[0]:+.2f} Fy={f[1]:+.2f} Fz={f[2]:+.2f}  '
                   f'위치{"O" if reached else "X"} 힘{"O" if force_ok else "X"}')
            if reached and force_ok:
                log(msg + '  -> 넣기 완료')
                finished = True
                break
            log(msg)
        else:
            log('[넣기] 끝까지 밀었는데 완료 아님')
    log(f'[넣기] 힘 요약: 최대 반력 {max_react:+.2f}N ({max_at:.0f}mm에서), 마지막 힘 변화 '
        f'dFx={last_f[0]:+.2f} dFy={last_f[1]:+.2f} dFz={last_f[2]:+.2f}N (기준 반력 {react_n}N)')
    grip_open()
    log('[넣기] 그리퍼 열기 (판재 놓음)' if finished
        else '[넣기] 완료 확인은 안 됐지만 그리퍼 열기 (판재 놓음) -> 결과 False')
    return finished


def _check_force_and_release(layer: int, log=print) -> bool:
    """(1층) 다가가기 마지막 fwd: 처음 SD_INSERT_CHECK_FROM_MM은 위치 제어, 나머지는 순응 제어로
    CHECK_STEP_MM씩 밀며 반력 > 기준이면 멈춤. 반력과 상관없이 놓고 True."""
    approach_sd(layer, log=log, skip_last=True)
    steps, pts = poses.SD_INSERT_APPROACH[layer], _approach_points(layer)
    start, last = pts[-2], pts[-1]
    kind, val = steps[-1]
    total = _dist(start, last)
    u = _push_dir(layer, last[3:6])
    react_n = _react_n(layer)
    free = min(getattr(poses, 'SD_INSERT_CHECK_FROM_MM', {}).get(layer, 0.0), total)

    log(f'  {len(steps)}/{len(steps)} {kind} {val:+g} -> {_r(last[:3])} '
        f'(처음 {free:.0f}mm 위치 제어, 나머지 {total - free:.0f}mm 순응 제어 {CHECK_STEP_MM:.0f}mm씩, '
        f'반력 > {react_n}N이면 멈추고 놓기)')
    d = 0.0
    if free > 0:
        movel(posx(*_point_on_line(start, last, free)), vel=INSERT_VELX, acc=INSERT_ACCX)
        d = free
        log(f'  [밀기 {d:.0f}/{total:.0f}mm] 위치 제어로 이동')
    wait(SETTLE_SEC)
    base = read_force_xyz()
    got = False
    with _compliance(layer, log):
        while d < total - 1e-9:
            d = min(d + CHECK_STEP_MM, total)
            movel(posx(*_point_on_line(start, last, d)), vel=PUSH_VELX, acc=PUSH_ACCX)
            react = _react(read_force_xyz(PUSH_FORCE_SAMPLES), base, u)
            got = react > react_n
            log(f'  [순응 밀기 {d:.0f}/{total:.0f}mm] 반력 {react:+.2f}N (기준 > {react_n}N)'
                f'{" -> 받음, 멈추고 놓기" if got else ""}')
            if got:
                break
    if not got:
        log(f'[넣기] {total:.0f}mm 끝까지 밀었는데 반력 {react_n}N 안 받음 -> 그대로 놓음')
    grip_open()
    log('[넣기] 그리퍼 열기 (판재 놓음)')
    return True


def approach_sd(layer: int, log=print, skip_last: bool = False) -> None:
    """sd 3 -> SD_INSERT_APPROACH[layer] 순서대로 다가가기. 이어지는 회전 단계는 한 번에 돌림.

    skip_last=True면 마지막 단계는 부르는 쪽(_check_force_and_release)이 힘을 재며 직접 간다.
    """
    if not _uses_approach(layer):
        raise ValueError(f'{layer}층은 다가가기 순서(SD_INSERT_APPROACH)가 없음 (가능: {list(poses.SD_INSERT_APPROACH)})')
    steps = poses.SD_INSERT_APPROACH[layer]
    pts = _approach_points(layer)
    log(f'[넣기] {layer}층: sd 3에서 다가가기 {steps}')
    _movel_slow(poses.SD_POS_X[poses.SD_TOP_LAYER], 'sd 3')
    for i, ((kind, val), pt) in enumerate(zip(steps, pts), 1):
        if skip_last and i == len(steps):
            break
        if kind in _ROT and i < len(steps) and steps[i][0] in _ROT:
            log(f'  {i}/{len(pts)} {kind} {val:+g} (다음 회전과 같이)')
            continue
        log(f'  {i}/{len(pts)} {kind} {val:+g} -> {_r(pt[:3])}' + (f' 자세 {_r(pt[3:6], 2)}' if kind in _ROT else ''))
        _movel_slow(pt, f'다가가기 {i}단계', rotate=kind in _ROT)


def _uses_approach(layer: int) -> bool:
    return layer in getattr(poses, 'SD_INSERT_APPROACH', {})


def _approach_points(layer: int) -> list:
    """sd 3에서 SD_INSERT_APPROACH[layer] 순서대로 간 점들 (마지막 = 입구). fwd는 그때 그리퍼 방향."""
    p = list(poses.SD_POS_X[poses.SD_TOP_LAYER])
    pts = []
    for kind, val in poses.SD_INSERT_APPROACH[layer]:
        if kind == 'fwd':
            d = _tool_z_dir(p[3:6])
            p[:3] = [p[i] + d[i] * val for i in range(3)]
        elif kind in ('x', 'y', 'z'):
            p['xyz'.index(kind)] += val
        elif kind in _ROT:
            p = p[:3] + rotate_about_base(kind[1], p[3:6], val)
        else:
            raise ValueError(f'SD_INSERT_APPROACH 단계 종류를 모름: {kind} (fwd / x / y / z / rx / ry / rz)')
        pts.append(list(p))
    return pts


def _insert_pre(layer: int) -> list:
    """넣기 첫 점 (여기서 멈춤). 다가가기 층은 입구, 그 외는 SD_PRE_INSERT_X."""
    if _uses_approach(layer):
        return _approach_points(layer)[-1]
    return list(poses.SD_PRE_INSERT_X[layer])


def _insert_line(layer: int) -> tuple[list, list, list, float]:
    """넣는 직선 (입구, 끝, 방향 단위벡터, 길이 mm)."""
    if _uses_approach(layer):
        _need(layer, (poses.SD_INSERT_DONE_X, 'SD_INSERT_DONE'))
        front = _approach_points(layer)[-1]
    else:
        _need(layer, (poses.SD_PRE_INSERT_X, 'SD_PRE_INSERT'), (poses.SD_INSERT_FRONT_X, 'SD_INSERT_FRONT'),
              (poses.SD_INSERT_DONE_X, 'SD_INSERT_DONE'))
        front = list(poses.SD_INSERT_FRONT_X[layer])
    done = list(poses.SD_INSERT_DONE_X[layer])
    length = _dist(front, done)
    return front, done, [(done[i] - front[i]) / length for i in range(3)], length


def _insert_move(pose_x: list, base: list, log, label: str,
                 vel: float = INSERT_VELX, acc: float = INSERT_ACCX) -> None:
    """movel 후 X/Y 힘 변화 확인. JAM_FORCE_N 이상이면 걸린 것 -> 예외 (잡은 채로)."""
    movel(posx(*pose_x), vel=vel, acc=acc)
    f = read_force_xyz()
    dfx, dfy = f[0] - base[0], f[1] - base[1]
    log(f'  [{label}] X={pose_x[0]:.1f} Y={pose_x[1]:.1f}  dFx={dfx:+.1f}N dFy={dfy:+.1f}N')
    if max(abs(dfx), abs(dfy)) >= JAM_FORCE_N:
        raise RuntimeError(f'넣다가 걸림 ({label}: dFx={dfx:+.1f}N dFy={dfy:+.1f}N, '
                           f'기준 {JAM_FORCE_N}N) -> 멈춤, 그리퍼는 잡은 상태')


def _keep_z(layer: int) -> bool:
    return bool(getattr(poses, 'SD_INSERT_KEEP_Z', {}).get(layer))


def _push_dir(layer: int, ori: list) -> list:
    """미는 방향 단위벡터. SD_INSERT_KEEP_Z 층은 수평으로 눕힘 (높이 유지)."""
    d = _tool_z_dir(ori)
    if _keep_z(layer):
        n = math.hypot(d[0], d[1])
        d = [d[0] / n, d[1] / n, 0.0]
    return d


def _react_n(layer: int) -> float:
    return getattr(poses, 'SD_DONE_REACT_N', {}).get(layer, DONE_REACT_N)


def _react(f: list, base: list, u: list) -> float:
    """미는 방향 반력 (기준 대비, + = 막혀서 밀림)."""
    return -sum((f[i] - base[i]) * u[i] for i in range(3))


@contextmanager
def _compliance(layer: int, log=print):
    """순응 제어 구간. 강성 X = 끝 + PUSH_OVERSHOOT_MM에서 PUSH_FORCE_N, KEEP_Z 층은 Z 최대.

    나올 때(예외여도) 해제 -> 그리퍼 열기 전에 순응을 풀어 눌린 힘에 손목이 튀지 않게.
    """
    stx = list(COMPLIANCE_STX)
    stx[0] = PUSH_FORCE_N / (PUSH_OVERSHOOT_MM / 1000.0)
    if _keep_z(layer):
        stx[2] = KEEP_Z_STIFF_N_M
    log(f'[넣기] 순응 강성 {[round(v) for v in stx[:3]]}N/m (X {stx[0] / 1000:.2f}N/mm'
        f'{", Z 고정" if _keep_z(layer) else ""})')
    task_compliance_ctrl(stx=stx)
    try:
        wait(0.3)
        yield
    finally:
        release_compliance_ctrl()


# ---- 2-6. Load2 (4) 놓은 뒤 빼기 (끝나면 run_load2가 바로 홈)
def retreat_sd(layer: int = 3, log=print) -> None:
    """poses.SD_RETREAT_STEPS[layer] 순서로 빼기. 그리퍼 그대로.

    ('x'/'y'/'z', mm) 직선 (QUICK_RETREAT_VELX) / ('entrance', 0) 넣은 직선 따라 입구까지 (INSERT_VELX).
    """
    steps = getattr(poses, 'SD_RETREAT_STEPS', {}).get(layer)
    if not steps:
        raise ValueError(f'SD_RETREAT_STEPS에 {layer}층 순서 없음')
    log(f'[빼기] {layer}층 빼기 {steps} -> 홈')
    for i, (kind, val) in enumerate(steps, 1):
        if kind == 'entrance':
            front = _insert_line(layer)[0]
            log(f'  {i}/{len(steps)} 입구까지 {_r(front[:3])}')
            _movel_slow(front, '입구')
        else:
            log(f'  {i}/{len(steps)} {kind} {val:+g}')
            _rel_step(kind, val, log=log, vel=QUICK_RETREAT_VELX)


# ============================================================================
# PART 3. Unload - 작업대에서 판재 꺼내기  (※ 다른 사람 작업, 코드 그대로)
# ============================================================================

# ---- 3-1. 액션 진입점
_last_unload_layer: int | None = None


def run_unload1(goal: Unload1.Goal, log=print) -> bool:
    """Unload1: 홈 -> 진입전2 -> 작업대(sd_pos_id층) -> 잡고 -X 당겨 턱 걸림 확인.

    반환값: 베드판을 잡아 턱에 걸리는 힘이 감지됐으면 True (당긴 채로 멈춤),
            감지되지 않았으면 원위치 복귀 및 그리퍼 열기 후 진입전2 -> ... -> 홈으로 역순 복귀하고 False.
    좌표 없는 층 번호가 오면 움직이기 전에 실패(예외) 처리된다.
    """
    global _last_unload_layer
    layer = goal.sd_pos_id
    table = getattr(unload_poses, 'UNLOAD_J', {})
    layers = getattr(unload_poses, 'UNLOAD_LAYER_STEP', {})
    frm = getattr(unload_poses, 'UNLOAD_BRANCH_FROM', None)
    if layer not in layers:
        raise ValueError(f'UNLOAD_LAYER_STEP에 {layer}층 없음 (가능: {sorted(layers)})')
    if frm not in table:
        raise ValueError(f'UNLOAD_J에 진입전2({frm}) 좌표 없음')
    nums = [n for n in sorted(table) if 1 <= n <= frm]
    if not nums:
        raise ValueError(f'UNLOAD_J에 시작~진입전2({frm}) 좌표 없음')
    target_step = layers[layer]
    if target_step not in table:
        raise ValueError(f'UNLOAD_J에 {layer}층({target_step}번) 좌표 없음')

    _last_unload_layer = layer
    log(f'[unload1] 작업대 {layer}층')
    for idx, n in enumerate(nums):
        unload_move_step(n, log=log)
        if idx == 0:
            grip_open()
    unload_enter_layer(layer, log=log)
    log(f'  언로드{layer} 도착 -> {UNLOAD_ARRIVE_WAIT_SEC:.0f}초 대기 후 잡기')
    wait(UNLOAD_ARRIVE_WAIT_SEC)
    if unload_grab_pull(layer, log=log):
        return True
    unload_retreat_home(layer, log=log)   # 못 잡음 -> 진입전2 -> ... -> 홈으로 역순 복귀
    return False


def run_unload2(goal: Unload2.Goal, log=print, layer: int | None = None) -> bool:
    """Unload2: (Unload1로 베드판을 잡은 상태에서) 빼내기 -> 수령대(receive_pos_id) -> 놓기 -> 홈 복귀.

    1) UNLOAD_EXTRACT_STEPS[layer] 순서로 베드 빼내기
       (UNLOAD_MOVEL_FROM_STEP 이전은 movej, 이후는 UNLOAD_USE_MOVEL에 따라 movel)
    2) UNLOAD_RECV_J[receive_pos_id] 순서로 수령대 이동 (직전 좌표와 같으면 생략)
    3) grip_open()으로 수령대에 베드판 놓기
    4) 복귀 경로(unload_poses.unload_return_path(receive_pos_id))를 movesj 한 번으로 홈 복귀
    좌표가 없는 수령대 번호나 추출 경로가 없는 층이면 움직이기 전에 예외 처리된다.
    """
    receive_pos_id = goal.receive_pos_id
    recv_table = getattr(unload_poses, 'UNLOAD_RECV_J', {})
    if receive_pos_id not in recv_table:
        raise ValueError(
            f'UNLOAD_RECV_J에 수령대 {receive_pos_id}번 좌표 없음 (가능: {sorted(recv_table)})'
        )

    extract_table = getattr(unload_poses, 'UNLOAD_EXTRACT_STEPS', {})
    target_layer = _last_unload_layer if layer is None else layer
    if target_layer is None:
        if len(extract_table) == 1:
            target_layer = next(iter(extract_table))
            log(f'[unload2] 직전 unload1 층 정보 없음 -> 유일한 추출 경로({target_layer}층) 사용')
        else:
            raise ValueError('직전 unload1 층 정보가 없어 추출 경로를 결정할 수 없음')

    steps = list(extract_table.get(target_layer, []))
    if not steps:
        raise ValueError(
            f'UNLOAD_EXTRACT_STEPS에 {target_layer}층 좌표 없음 (가능: {sorted(extract_table)})'
        )

    table = getattr(unload_poses, 'UNLOAD_J', {})
    for n in steps:
        if n not in table:
            raise ValueError(f'UNLOAD_J에 {n}번 좌표 없음 (가능: {sorted(table)})')

    movel_from = getattr(unload_poses, 'UNLOAD_MOVEL_FROM_STEP', 10)

    log(f'[unload2] 작업대 {target_layer}층 빼내기 -> 수령대 {receive_pos_id}번')
    for n in steps:
        linear = UNLOAD_USE_MOVEL and n >= movel_from
        unload_move_step(n, log=log, linear=linear)

    last_j = table[steps[-1]][1]
    for name, jj in recv_table[receive_pos_id]:
        if list(jj) == list(last_j):
            log(f'  {name}: 지금 위치와 같은 좌표 -> 이동 생략')
            continue
        unload_move_j(name, jj, log=log)

    unload_recv_wiggle(log=log)
    log(f'  수령대{receive_pos_id} 도착 -> 그리퍼 열기 (놓기)')
    grip_open()

    unload_return_home(receive_pos_id, log=log)

    log(f'[unload2] 수령대{receive_pos_id} 전달 후 홈 복귀 완료')
    return True


def run_unload(goal: Unload.Goal, log=print) -> bool:
    """Unload: 아직 동작 없음. 홈 위치로만 이동."""
    go_home()
    return True


# ---- 3-2. 언로드 이동 / 잡고 당기기 / 수령대 / 복귀
def unload_move_step(n: int, log=print, linear: bool = False) -> None:
    """UNLOAD_J[n] 좌표로 이동. linear=True면 movel(직선), 아니면 movej(관절).
    속도/가속도 비율은 unload_poses.UNLOAD_STEP_SPEED[n] (없으면 1.0 / 1.0)."""
    table = unload_poses.UNLOAD_J
    if n not in table:
        raise ValueError(f'{n}번 좌표 없음 (가능: {sorted(table)})')
    name, j = table[n]
    vs, as_ = getattr(unload_poses, 'UNLOAD_STEP_SPEED', {}).get(n, (1.0, 1.0))
    unload_move_j(f'[{n}] {name}', j, log=log, linear=linear, vel_scale=vs, acc_scale=as_)


def unload_move_j(name: str, j, log=print, linear: bool | None = None,
                  vel_scale: float = 1.0, acc_scale: float = 1.0) -> None:
    """이름 붙은 posj 좌표로 이동 (베드 빼내기 / 수령대 / 복귀용).

    linear가 None이면 UNLOAD_USE_MOVEL을 따른다. movel은 posj를 fkin으로 posx로 바꿔서 직선 이동.
    vel_scale / acc_scale: 기본 속도/가속도에 곱하는 비율 (천천히, 부드럽게 가려면 1보다 작게)."""
    if linear is None:
        linear = UNLOAD_USE_MOVEL
    if linear:
        vel, acc = UNLOAD_VELX * vel_scale, UNLOAD_ACCX * acc_scale
        x = fkin(posj(*j), ref=DR_BASE)
        log(f'  {name}: movel posj={list(j)} -> posx={[round(float(v), 2) for v in x]}  (vel={vel:.1f} acc={acc:.1f})')
        movel(x, vel=vel, acc=acc)
    else:
        vel, acc = UNLOAD_VELJ * vel_scale, UNLOAD_ACCJ * acc_scale
        log(f'  {name}: movej posj={list(j)}  (vel={vel:.1f} acc={acc:.1f})')
        movej(posj(*j), vel=vel, acc=acc)


def unload_return_path(receive_pos_id: int) -> list:
    """수령대 receive_pos_id에서 홈까지 복귀 경로 [(이름, posj), ...].
    unload_poses.unload_return_path: 수령대별 앞부분(UNLOAD_RETURN_HEAD_J) + 공통 끝부분(UNLOAD_RETURN_TAIL_J)."""
    return unload_poses.unload_return_path(receive_pos_id)


def unload_return_home(receive_pos_id: int, log=print, start: int = 1) -> None:
    """그리퍼를 연 뒤 복귀 경로 전체를 movesj 한 번으로 이동 (경유점에서 멈추지 않는 관절 스플라인).
    바로 앞 좌표와 같은 좌표는 빼고 넘긴다 (스플라인에 같은 점이 연속이면 안 됨).
    start: 복귀 경로의 몇 번째 점(1부터)부터 갈지 (테스트용, 기본 = 처음부터)."""
    path = unload_return_path(receive_pos_id)[max(start, 1) - 1:]
    pts, names = [], []
    for name, j in path:
        if pts and list(j) == list(pts[-1]):
            log(f'  {name}: 바로 앞 좌표와 같음 -> 경유점에서 뺌')
            continue
        pts.append(list(j))
        names.append(name)
    if not pts:
        return
    log(f'  [복귀] 수령대{receive_pos_id} -> 홈 movesj {len(pts)}점 '
        f'(vel={UNLOAD_RETURN_VELJ} acc={UNLOAD_RETURN_ACCJ}): {" -> ".join(names)}')
    movesj([posj(*j) for j in pts], vel=UNLOAD_RETURN_VELJ, acc=UNLOAD_RETURN_ACCJ)


def unload_recv_wiggle(log=print) -> None:
    """수령대에서 놓기 전에 좌우로 흔들어 자리 맞추기: 중심 -> +mm -> -mm -> 중심 (base 기준 상대 이동)."""
    i = _TASK_AXIS_INDEX[UNLOAD_WIGGLE_AXIS]
    mm = UNLOAD_WIGGLE_MM
    log(f'  [자리 맞추기] base {UNLOAD_WIGGLE_AXIS} ±{mm:.0f}mm 좌우 이동 (vel={UNLOAD_WIGGLE_VELX} acc={UNLOAD_WIGGLE_ACCX})')
    for d in (mm, -2 * mm, mm):   # +mm, (반대쪽) -mm, 다시 중심
        delta = [0.0] * 6
        delta[i] = d
        movel(posx(*delta), vel=UNLOAD_WIGGLE_VELX, acc=UNLOAD_WIGGLE_ACCX, ref=DR_BASE, mod=DR_MV_MOD_REL)


def unload_move_pre(layer: int, log=print) -> None:
    """언로드 layer층 진입전 좌표로 관절 이동 (없거나 진입전2와 같으면 생략)."""
    pre = getattr(unload_poses, 'UNLOAD_PRE_J', {}).get(layer)
    if pre is None:
        return
    name, j = pre
    frm = getattr(unload_poses, 'UNLOAD_BRANCH_FROM', None)
    if frm in unload_poses.UNLOAD_J and list(j) == list(unload_poses.UNLOAD_J[frm][1]):
        log(f'  {name}: 진입전2와 같은 좌표 -> 이동 생략')
        return
    log(f'  {name}: posj={j}  (vel={UNLOAD_VELJ} acc={UNLOAD_ACCJ})')
    movej(posj(*j), vel=UNLOAD_VELJ, acc=UNLOAD_ACCJ)


def unload_enter_layer(layer: int, log=print) -> None:
    """진입전2 -> (층 진입전) -> 언로드 layer층."""
    unload_move_pre(layer, log=log)
    unload_move_step(unload_poses.UNLOAD_LAYER_STEP[layer], log=log)


def unload_leave_layer(layer: int, log=print) -> None:
    """언로드 layer층 -> (층 진입전) -> 진입전2."""
    unload_move_pre(layer, log=log)
    unload_move_step(unload_poses.UNLOAD_BRANCH_FROM, log=log)


def unload_retreat_home(layer: int, log=print) -> None:
    """잡기 실패 후 올 때 길을 역순으로: 언로드 layer층 -> (층 진입전) -> 진입전2 -> ... -> 진입전1 -> 홈."""
    frm = unload_poses.UNLOAD_BRANCH_FROM
    log(f'  [복귀] 언로드{layer} 잡기 실패 -> 왔던 길을 거꾸로 홈까지')
    unload_leave_layer(layer, log=log)
    for n in sorted((k for k in unload_poses.UNLOAD_J if k < frm), reverse=True):
        unload_move_step(n, log=log)


def unload_grab_pull(layer: int, log=print) -> bool:
    """베드판을 잡고 -X로 당겨 턱에 걸리는 힘이 들어오는지 확인.

    잡았으면 True(당겨진 위치에서 멈춤), 못 잡았으면 원위치로 돌아가 그리퍼를 열고 False.
    """
    start = list(get_current_poses()[1])
    pos_mm = UNLOAD_PULL_POS_MM
    total_mm = UNLOAD_PULL_POS_MM + UNLOAD_PULL_COMPLIANCE_MM
    log(f'  [당기기] 언로드{layer}: 원위치 X={start[0]:.1f} Y={start[1]:.1f} Z={start[2]:.1f} '
        f'-> 그리퍼 닫고 -X 최대 {total_mm:.0f}mm (위치 제어 {pos_mm:.0f}mm + 순응 {UNLOAD_PULL_COMPLIANCE_MM:.0f}mm)')
    grip_close()
    wait(UNLOAD_SETTLE_SEC)

    def goto_x(x: float, vel: float, acc: float) -> list[float]:
        t = list(start)
        t[0] = x
        movel(posx(*t), vel=vel, acc=acc)
        return t

    t = goto_x(start[0] - pos_mm, UNLOAD_PULL_VELX, UNLOAD_PULL_ACCX)
    cur = list(get_current_poses()[1])
    if abs(cur[0] - t[0]) > UNLOAD_PULL_REACH_TOL_MM:
        raise RuntimeError(f'당기는 목표에 못 감 (NOT REACHABLE?) 목표 X={t[0]:.1f} 현재 X={cur[0]:.1f}')
    wait(UNLOAD_SETTLE_SEC)
    base = read_force_xyz(UNLOAD_PULL_FORCE_SAMPLES)
    log(f'  [당기기] 위치 제어 {pos_mm:.0f}mm 완료 (X={cur[0]:.1f}). '
        f'기준 힘 Fx={base[0]:+.2f} Fy={base[1]:+.2f} Fz={base[2]:+.2f} N')

    caught = False
    task_compliance_ctrl(stx=list(COMPLIANCE_STX))
    try:
        wait(0.3)
        done = 0.0
        while done < UNLOAD_PULL_COMPLIANCE_MM - 1e-9:
            done = min(done + UNLOAD_PULL_STEP_MM, UNLOAD_PULL_COMPLIANCE_MM)
            goto_x(start[0] - pos_mm - done, UNLOAD_PULL_VELX, UNLOAD_PULL_ACCX)
            f = read_force_xyz(UNLOAD_PULL_FORCE_SAMPLES)
            cur = list(get_current_poses()[1])
            dfx = f[0] - base[0]
            hit = abs(dfx) >= UNLOAD_CATCH_FORCE_N
            log(f'  [당기기 순응 {done:.0f}/{UNLOAD_PULL_COMPLIANCE_MM:.0f}mm] X={cur[0]:.1f}  '
                f'dFx={dfx:+.2f}N  Fx={f[0]:+.2f} Fy={f[1]:+.2f} Fz={f[2]:+.2f}  '
                f'(기준 {UNLOAD_CATCH_FORCE_N}N) 턱{"O" if hit else "X"}')
            if hit:
                caught = True
                break
    finally:
        release_compliance_ctrl()

    if caught:
        return True
    log(f'  [당기기] 끝까지 당겨도 턱에 걸리는 힘 없음 -> 원위치(X={start[0]:.1f})로 되돌아감')
    movel(posx(*start), vel=UNLOAD_PULL_VELX, acc=UNLOAD_PULL_ACCX)
    grip_open()
    return False


# ============================================================================
# PART 4. 조그 / 그리퍼  (※ 다른 사람 작업 - 티칭 팬던트, 코드 그대로)
# ============================================================================
# 조그는 힘 기반 안전장치(무게 감지, 걸림 감지)가 없는 자유공간 이동이라
# LOAD/UNLOAD 기본값보다 더 낮게 둔다 (부모 PRD 9장: "절반 이하" 권장보다 더 낮춤).
JOG_VELJ, JOG_ACCJ = 15.0, 15.0     # deg, deg/s^2  (기존 VELJ/ACCJ=30의 절반)
JOG_VELX, JOG_ACCX = 30.0, 30.0     # mm/s, mm/s^2  (기존 VELX/ACCX=100의 1/3 - 힘 감지 없음 고려)

# 부모 PRD 9장 상한과 동일 (안전 마진을 줄이지 않고, ROS 2 쪽에서 한 번 더 검증)
JOG_MAX_LINEAR_MM = 20.0
JOG_MAX_ROT_DEG = 15.0
JOG_MAX_JOINT_DEG = 15.0

_TASK_AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2, 'RX': 3, 'RY': 4, 'RZ': 5}
_JOINT_AXIS_INDEX = {f'J{i + 1}': i for i in range(6)}
_REF_FRAME = {'BASE': DR_BASE, 'TOOL': DR_TOOL}


class JogRejected(Exception):
    """스텝 상한 초과 등 실행 전 검증 실패 (모션 자체는 일어나지 않음)."""


def run_jog(goal: 'Jog.Goal', log=print) -> tuple[bool, list[float], list[float]]:
    """goal(space/ref_frame/axis/direction/step_size)을 실제 이동으로 변환.

    반환: (성공 여부, posj[6], posx[6]) - 실패해도 현재 위치는 돌려준다(웹 표시용).

    space='TASK'/'JOINT', ref_frame='BASE'/'TOOL'(TASK일 때만), axis는
    TASK: X/Y/Z/RX/RY/RZ, JOINT: J1..J6. 상한 초과나 알 수 없는 값은
    JogRejected로 거절한다(모션 전 검증, 로봇은 움직이지 않음).

    PRD 4.2 Plan A(네이티브 mod=DR_MV_MOD_REL 상대 이동)를 그대로 쓴다. 이 머신에는
    DSR_ROBOT2가 설치돼 있지 않아 movej/movel의 mod/ref 키워드 인자를 실제로
    import-level로 검증하지 못했다 - 실제 로봇/시뮬레이터 연결 환경에서 반드시
    재확인할 것 (모듈 상단 주석, PRD 1장/9장 참고).
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
        log(f'[jog] JOINT {axis} {"+" if direction > 0 else "-"}{step}deg')
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
        log(f'[jog] TASK {axis} {"+" if direction > 0 else "-"}{step} ref={goal.ref_frame}')
        movel(posx(*delta), vel=JOG_VELX, acc=JOG_ACCX, ref=ref, mod=DR_MV_MOD_REL)

    else:
        raise JogRejected(f'알 수 없는 space: {space}')

    posj_vals, posx_vals = get_current_poses()
    return True, posj_vals, posx_vals


def run_gripper(goal: 'Gripper.Goal', log=print) -> tuple[bool, str]:
    """goal.action('OPEN'|'CLOSE')에 따라 그리퍼 개폐.

    항상 성공(True)으로 본다(파지 피드백은 부모 PRD 1장 범위 밖 - 디지털 출력을
    내리는 것 자체는 실패할 수 있는 지점이 거의 없음).
    """
    action = goal.action
    log(f'[gripper] {action}')
    if action == 'OPEN':
        grip_open()
    elif action == 'CLOSE':
        grip_close()
    else:
        raise ValueError(f'알 수 없는 gripper action: {action}')
    return True, action
