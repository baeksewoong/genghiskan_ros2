# motions_refactor.py - motions.py(2026-11-20 main 기준)를 정리한 리뷰용 사본.
# 함수 순서 재배치 + 주석 정리 + 안 쓰는 상수/꺼 둔 기능 삭제. 액션 동작(로봇 명령 순서/값)은 motions.py와 같다
# (가짜 로봇으로 load1/load2/inpush 46개 상황 비교). motion_test의 wtest, sda, sdain은 이 파일로는 안 됨.
# 어디서도 import 하지 않는다. 실제 동작 파일은 motions.py. 설명: motions_refactor.md
# 구성: PART 1 공통 / PART 2 Load / PART 3 Unload (※ 다른 사람 작업) / PART 4 조그·그리퍼 (※ 다른 사람 작업)
"""로봇 구체 동작 (Load / Unload).

robot_action_server.py가 goal을 받으면 여기의 run_*()를 호출한다.
True(또는 None) = 성공, False = 실패, 예외 = 실패 (message에 예외 내용).

주의: DSR_ROBOT2를 맨 위에서 import 하므로 DR_init 설정이 끝난 뒤에만 import 된다 (단독 실행 불가).
"""
from __future__ import annotations

from DR_common2 import posj, posx
import math

from DSR_ROBOT2 import (
    DR_AXIS_Z,
    DR_BASE,
    DR_MV_MOD_REL,
    DR_TOOL,
    OFF,
    ON,
    align_axis,
    fkin,
    get_current_posj,
    get_current_posx,
    get_tool_force,
    movej,
    movel,
    release_compliance_ctrl,
    set_digital_output,
    task_compliance_ctrl,
    wait,
)
# -------------------------------------------------------------------------
# DR_MV_MOD_REL / DR_TOOL 검증 메모 (2026-11-18):
# 이 개발 머신에는 DSR_ROBOT2가 설치돼 있지 않아(`python3 -c "import DSR_ROBOT2"` ->
# ModuleNotFoundError) 실제 설치본에서 이 심볼들이 존재하는지 import 레벨로 확인하지
# 못했다. 두산 공식 DRL 매뉴얼(movel/movej 문서, PRD 1장 참고 링크)상으로는 이
# 이름들이 맞고, movel/movej의 mod=DR_MV_MOD_REL 상대 이동과 ref=DR_TOOL 툴
# 좌표계 기준 이동이 공식 예제에 나온다 (Plan A). 실제 로봇/시뮬레이터(DRCF)가
# 연결된 환경에서 ImportError가 나면, 설치된 DSR_ROBOT2 버전의 실제 심볼명을
# 확인해 아래 run_jog()와 함께 고쳐야 한다 (PRD 9장 미결 사항, Plan B로
# 전환할지도 그때 재판단).
# (DR_QSTOP/DR_SSTOP/stop은 여기서 쓰지 않는다 - PRD 5.3대로 /sfarm/jog/stop
# 서비스가 motions.py를 거치지 않고 robot_action_server.py에서 직접
# DSR_ROBOT2를 import해 호출한다.)
# -------------------------------------------------------------------------

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
VELJ, ACCJ = 30.0, 30.0      # 관절 이동 (movej)
VELX, ACCX = 100.0, 100.0    # 직선 이동 (movel)
# 빈손 이동 속도 (홈 -> 적재대 다가가기, 판재 내려놓고 빠지기, load2 끝 홈 복귀)
EMPTY_VELJ, EMPTY_ACCJ = 100.0, 100.0   # 빈손 movej (홈, 준비 자세, 홈 복귀)
EMPTY_VELX, EMPTY_ACCX = 100.0, 100.0
# 판재 들고 이동 (잡고 30mm 들기, 적재대 빼기, sd 3으로 movej)
CARRY_VELJ, CARRY_ACCJ = 60.0, 60.0
CARRY_VELX, CARRY_ACCX = 60.0, 60.0
# 놓은 뒤 짧게 빼기 속도 (SD_RETREAT_STEPS의 x/y/z 단계)
QUICK_RETREAT_VELX = 60.0
# 프린터 안 (다가가기, 직선 넣기, 빼기, sd 3 첫 점/입구)은 INSERT_VELX(30). 마지막 순응 밀기만 PUSH_VELX(10).

# 준비 -> 진입 전 -> 적재대 이동: True = movel, False = movej (movel에서 문제 생기면 False로)
USE_MOVEL = True

# ---------------------------------------------------------------- 집기 / 무게 감지
LIFT_Z_MM = 30.0           # 잡은 뒤 들어 올리는 높이 (+Z, mm)
# 판재 확인: 들어 올린 뒤 ry로 숙이면 판재 끝이 선반을 눌러 Fz가 덜 음수가 됨 -> 숙인 뒤 Fz로 판정.
#   3층 실측: 있음 -11.66 ~ -12.06N, 없음 -12.70 ~ -13.06N -> -12.4N (층별 값은 poses.TILT_CHECK_*_BY_LAYER)
TILT_CHECK_DEG = 9.0       # 숙이는 각도 (도). 판재 끝(약 215mm)이 약 34mm 내려가 선반에 닿음
TILT_CHECK_FZ_N = -12.4    # 숙인 뒤 Fz가 이 값보다 크면 판재 있음
TILT_CHECK_SETTLE_SEC = 1.0  # 숙이기 전/후 힘 재기 전 기다리는 시간 (s)
TILT_CHECK_SAMPLES = 10    # 힘 평균 횟수 (FORCE_SAMPLE_INTERVAL 0.1s 간격 -> 약 1초)
FORCE_SAMPLES = 5          # 힘 측정 평균 낼 횟수
FORCE_SAMPLE_INTERVAL = 0.1  # 측정 간격 (s)
SETTLE_SEC = 0.5           # 움직임이 끝나고 힘을 재기 전 기다리는 시간 (s)

# movel 도착 확인 허용 오차 (mm). 못 가는 좌표면 movel이 에러 없이 넘어가서 이동 뒤 위치로 확인.
REACH_TOL_MM = 3.0

# ---------------------------------------------------------------- 판재 빼기
PULL_OUT_MM = 230.0        # 들어 올린 뒤 -X로 빼는 거리 (판재 길이 + 여유 15mm)

# ---------------------------------------------------------------- 작업대에 판재 넣기
INSERT_VELX, INSERT_ACCX = 30.0, 30.0   # 프린터 안 이동 (다가가기, 직선, 빼기)
ROT_VELX_DEG, ROT_ACCX_DEG = 5.0, 5.0   # insert/retreat 다가가기의 회전 단계(rx/ry/rz) 회전 속도 (도/s, 천천히)
ROT_WAIT_SEC = 0.5                      # 그 회전이 끝난 뒤 잠깐 멈춤 (s) - 팍팍 튀지 않게
STRAIGHT_VELX, STRAIGHT_ACCX = 30.0, 30.0  # 입구 -> 끝 직선으로 넣을 때 속도 (프린터 안 = 30)
# 넣는 길: 입구(SD_INSERT_FRONT) -> 끝(SD_INSERT_DONE) 직선 (측정한 자세 그대로).
JAM_FORCE_N = 20.0         # 위치 이동 중 X/Y 힘 변화가 이 값 넘으면 걸림 -> 멈춤 (놓지 않음)
PUSH_START_BEFORE_MM = 10.0  # 끝 이만큼 앞까지는 위치 제어로 일자로 넣고, 거기서부터 순응 제어로 밀기
PUSH_OVERSHOOT_MM = 15.0   # 끝보다 이만큼 더까지 (같은 직선 방향으로) 순응 제어 목표를 보냄 (그래도 완료 아니면 실패)
PUSH_FORCE_N = 5.0         # 끝에 닿은 채로 목표가 끝 + PUSH_OVERSHOOT_MM까지 가면 이 힘(N)으로 누르게 강성 자동 계산
PUSH_STEP_MM = 5.0         # 순응 제어로 밀 때 이만큼씩 끊어 가며 매번 확인
PUSH_VELX, PUSH_ACCX = 10.0, 10.0  # 순응 제어로 밀 때 속도 (아주 느리게)
PUSH_FORCE_SAMPLES = 2     # 한 번 재는 횟수 (적을수록 빠름)
# 넣기 완료 판정: 위치와 힘 둘 다 맞으면 완료 -> 그리퍼 열기
DONE_POS_TOL_MM = 2.0      # 직선 위 진행 거리가 끝 - 이 값 이상이면 '위치 도착'
DONE_REACT_N = 1.0         # 미는 방향 반력(기준 대비)이 이 값 이상이면 '힘 맞음' (PUSH_FORCE_N보다 작아야 함)
# 밀 때 순응 강성 (N/m, Nm/rad). 첫 값(X, 미는 방향)은 insert에서 PUSH_FORCE_N으로 다시 계산해서 덮어씀.
COMPLIANCE_STX = [500, 3000, 3000, 200, 200, 200]
# 축정렬: 툴 Z축을 +X에 맞춤 (motion_test 전용, load2 액션은 안 씀)
ALIGN_VECT = [1.0, 0.0, 0.0]   # 베이스 기준 미는 방향 (+X)
ALIGN_MAX_DEG = 15.0           # 지금 툴 Z축과 이 각도보다 많이 다르면 정렬 안 하고 멈춤 (안전)
PRE_INSERT_HOLD_SEC = 3.0      # sd 다음 첫 점(SD_PRE_INSERT)에서 멈추는 시간 (s)

# ---------------------------------------------------------------- 작업대에서 판재 꺼내기 (Unload1)
UNLOAD_VELJ, UNLOAD_ACCJ = 22.5, 22.5
UNLOAD_VELX, UNLOAD_ACCX = 67.5, 67.5
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


# ============================================================================
# PART 1. 공통 - 홈 / 그리퍼 / 힘 읽기 / 이동 도우미
# ============================================================================


# ---- 1-1. 홈, 그리퍼, 힘 읽기


def go_home(fast: bool = False) -> None:
    """홈(대기) 위치로 이동. fast=True면 빈손 속도(EMPTY_VELJ)."""
    v, a = (EMPTY_VELJ, EMPTY_ACCJ) if fast else (VELJ, ACCJ)
    movej(posj(*poses.HOME_J), vel=v, acc=a)


def grip_close() -> None:
    """그리퍼 닫기 (잡기)."""
    set_digital_output(1, ON)
    set_digital_output(2, OFF)
    wait(1.5)


def grip_open() -> None:
    """그리퍼 열기 (놓기)."""
    set_digital_output(1, OFF)
    set_digital_output(2, ON)
    wait(1.5)


def read_fz() -> float:
    """베이스 기준 툴 외력 Fz(N)를 여러 번 재서 평균."""
    total = 0.0
    for _ in range(FORCE_SAMPLES):
        total += float(get_tool_force(DR_BASE)[2])
        wait(FORCE_SAMPLE_INTERVAL)
    return total / FORCE_SAMPLES


def read_force_xyz(samples: int = FORCE_SAMPLES) -> list:
    """베이스 기준 툴 외력 [Fx, Fy, Fz](N) 평균."""
    total = [0.0, 0.0, 0.0]
    for _ in range(samples):
        f = get_tool_force(DR_BASE)
        for i in range(3):
            total[i] += float(f[i])
        wait(FORCE_SAMPLE_INTERVAL)
    return [v / samples for v in total]


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


# ---- 1-3. 이동 도우미 (도착 확인 / 느리게 / movej+movel)


class MotionStopped(Exception):
    """단계 진행 중 사용자가 멈춤 (motion_test의 board_step에서 사용)."""


def _movel_checked(pose_x: list, fast: bool = False, vel: float | None = None) -> None:
    """movel 후 목표 X, Y, Z에 도착했는지 확인 (못 가면 예외). fast=True면 빈손 속도, vel을 주면 그 속도."""
    v, a = (EMPTY_VELX, EMPTY_ACCX) if fast else (VELX, ACCX)
    if vel is not None:
        v = a = vel
    movel(posx(*pose_x), vel=v, acc=a)
    cur = list(get_current_posx()[0])
    err = max(abs(cur[i] - pose_x[i]) for i in range(3))
    if err > REACH_TOL_MM:
        raise RuntimeError(
            f'목표 위치에 못 감 (NOT REACHABLE?) 목표={[round(v, 1) for v in pose_x[:3]]} '
            f'현재={[round(v, 1) for v in cur[:3]]}')


def _movel_slow(target: list, name: str, rotate: bool = False) -> None:
    """INSERT_VELX로 movel + 도착 확인. rotate=True면 ROT_VELX_DEG로 천천히 돌리고 ROT_WAIT_SEC 멈춤."""
    if rotate:
        movel(posx(*target), vel=[INSERT_VELX, ROT_VELX_DEG], acc=[INSERT_ACCX, ROT_ACCX_DEG])
    else:
        movel(posx(*target), vel=INSERT_VELX, acc=INSERT_ACCX)
    now = list(get_current_posx()[0])
    err = max(abs(now[i] - target[i]) for i in range(3))
    if err > REACH_TOL_MM:
        raise RuntimeError(f'{name}까지 못 감: 목표={[round(v, 1) for v in target[:3]]} '
                           f'현재={[round(v, 1) for v in now[:3]]}')
    if rotate:
        wait(ROT_WAIT_SEC)


def _move_to(pose_j: list, pose_x: list, fast: bool = False) -> None:
    """USE_MOVEL에 따라 movel(posx) 또는 movej(posj)로 이동. fast=True면 빈손 속도."""
    if USE_MOVEL:
        _movel_checked(pose_x, fast=fast)
    else:
        if pose_j is None:
            raise ValueError('관절 좌표(J)가 없어 movej로 갈 수 없음 (USE_MOVEL=True로 쓰거나 J 측정)')
        v, a = (EMPTY_VELJ, EMPTY_ACCJ) if fast else (VELJ, ACCJ)
        movej(posj(*pose_j), vel=v, acc=a)


# ---- 1-4. 자세 계산과 상대 이동 (ZYZ, 베이스 축 회전, 미는 축)


def _zyz_to_mat(a: float, b: float, c: float) -> list:
    """두산 posx 자세 (A, B, C) = ZYZ 오일러(도) -> 3x3 회전행렬."""
    a, b, c = (math.radians(v) for v in (a, b, c))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb * cc - sa * sc, -ca * cb * sc - sa * cc, ca * sb],
            [sa * cb * cc + ca * sc, -sa * cb * sc + ca * cc, sa * sb],
            [-sb * cc, sb * sc, cb]]


def _mat_to_zyz(m: list) -> list:
    """3x3 회전행렬 -> ZYZ 오일러(도) [A, B, C]."""
    b = math.atan2(math.hypot(m[0][2], m[1][2]), m[2][2])
    if abs(math.sin(b)) < 1e-9:   # B = 0 또는 180 (특이점): C = 0으로 둠
        return [math.degrees(math.atan2(m[1][0], m[0][0])), math.degrees(b), 0.0]
    a = math.atan2(m[1][2], m[0][2])
    c = math.atan2(m[2][1], -m[2][0])
    return [math.degrees(a), math.degrees(b), math.degrees(c)]


def rotate_about_base(axis: str, abc: list, deg: float) -> list:
    """자세 abc를 베이스 axis('x'/'y'/'z')축으로 deg만큼 돌린 자세 [A, B, C] (위치는 안 바뀜)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    rot = {'x': [[1, 0, 0], [0, c, -s], [0, s, c]],
           'y': [[c, 0, s], [0, 1, 0], [-s, 0, c]],
           'z': [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    m = _zyz_to_mat(*abc)
    return _mat_to_zyz([[sum(rot[i][k] * m[k][j] for k in range(3)) for j in range(3)] for i in range(3)])


def move_rel(dx: float = 0.0, dy: float = 0.0, dz: float = 0.0, log=print, check: bool = True,
             vel: float = INSERT_VELX) -> None:
    """지금 자세 그대로 X/Y/Z로 mm 직선 이동 (INSERT_VELX). check=False면 못 가도 경고만."""
    cur = list(get_current_posx()[0])
    target = list(cur)
    target[0] += dx
    target[1] += dy
    target[2] += dz
    log(f'  [이동] {[round(v, 1) for v in cur[:3]]} -> {[round(v, 1) for v in target[:3]]} '
        f'(dX {dx:+.0f} dY {dy:+.0f} dZ {dz:+.0f})')
    movel(posx(*target), vel=vel, acc=vel)
    now = list(get_current_posx()[0])
    err = max(abs(now[i] - target[i]) for i in range(3))
    if err > REACH_TOL_MM:
        msg = (f'목표까지 못 감 (차이 {err:.1f}mm, 지금 {[round(v, 1) for v in now[:3]]}, '
               f'NOT REACHABLE일 수 있음)')
        if check:
            raise RuntimeError(msg)
        log(f'  [경고] {msg} -> 그대로 계속')


def tilt_base(axis: str, deg: float, log=print, check: bool = True) -> None:
    """그리퍼 끝 위치 그대로 베이스 axis('x'/'y'/'z')축으로 deg만큼 돌리기.

    그리퍼가 +X를 볼 때: rx = 좌우로 눕히기, ry = 앞쪽 숙이기(+)/들기(-), rz = 좌우로 돌리기.
    """
    cur = list(get_current_posx()[0])
    target = cur[:3] + rotate_about_base(axis, cur[3:6], deg)
    log(f'  [r{axis} {deg:+.1f}도] 자세 {[round(v, 2) for v in cur[3:6]]} -> {[round(v, 2) for v in target[3:6]]}')
    movel(posx(*target), vel=[INSERT_VELX, 10.0], acc=[INSERT_ACCX, 10.0])
    now = list(get_current_posx()[0])
    err = max(abs(now[i] - target[i]) for i in range(3))
    if err > REACH_TOL_MM:
        if check:
            raise RuntimeError(f'못 돌림 (위치 차이 {err:.1f}mm, NOT REACHABLE일 수 있음)')
        log(f'  [경고] 돌린 뒤 위치 차이 {err:.1f}mm -> 그대로 계속')


def tilt_ry(deg: float, log=print) -> None:
    """그리퍼 끝 위치 그대로 베이스 Y축으로 deg만큼 기울이기 (그리퍼가 +X를 볼 때 + = 판재 앞쪽 숙임)."""
    tilt_base('y', deg, log=log)


def _tool_z_dir(ori: list) -> list:
    """posx 자세(ZYZ 오일러, deg) -> 베이스 기준 툴 Z축 방향 단위벡터."""
    a, b = math.radians(ori[0]), math.radians(ori[1])
    return [math.cos(a) * math.sin(b), math.sin(a) * math.sin(b), math.cos(b)]


def move_tool_z(mm: float, log=print) -> None:
    """미는 축(툴 Z, 그리퍼가 보는 방향)으로 mm 직선 이동, 자세 그대로 (+ = 앞, - = 뒤). 못 가면 예외."""
    cur = list(get_current_posx()[0])
    z = _tool_z_dir(cur[3:6])
    target = [cur[i] + z[i] * mm for i in range(3)] + cur[3:6]
    log(f'  [미는 축 {mm:+.1f}mm] 방향 {[round(v, 3) for v in z]}: '
        f'{[round(v, 1) for v in cur[:3]]} -> {[round(v, 1) for v in target[:3]]}')
    movel(posx(*target), vel=INSERT_VELX, acc=INSERT_ACCX)
    now = list(get_current_posx()[0])
    err = max(abs(now[i] - target[i]) for i in range(3))
    if err > REACH_TOL_MM:
        raise RuntimeError(f'목표까지 못 감 (차이 {err:.1f}mm, 지금 {[round(v, 1) for v in now[:3]]}, '
                           f'NOT REACHABLE일 수 있음)')
    log(f'  도착: X={now[0]:.1f} Y={now[1]:.1f} Z={now[2]:.1f}')


# ============================================================================
# PART 2. Load - 적재대에서 판재 꺼내 작업대(sd)에 넣기
# ============================================================================


# ---- 2-1. 액션 진입점


def run_load1(goal: Load1.Goal, log=print) -> bool:
    """Load1 액션: 적재대에서 잡고 판재 확인 (_load1_common)."""
    return _load1_common(goal, 'load1', log=log)


def run_load(goal: Load.Goal, log=print) -> bool:
    """Load 액션: run_load1과 같은 동작."""
    return _load1_common(goal, 'load', log=log)   # 실패하면 내려놓고 홈 (run_load1과 같음)


def run_load2(goal: Load2.Goal, log=print) -> bool:
    """Load2 액션: (load1로 들어 올린 상태에서) 적재대 빼기 -> sd 이동 -> 넣기 -> 빼기 -> 홈.

    결과 = 넣기 완료 확인 여부 (확인 안 돼도 그리퍼는 열고 홈으로 간다).
    """
    layer = goal.sd_pos_id
    _check_sd_layer(layer)
    log(f'[load2] 빼기 -> 작업대 {layer}층')
    exit_rack(log=log)
    go_sd(layer, log=log)   # 층별 순서로 뺐으면 그 끝 위치라서 적재대 안전 확인 통과
    if layer not in poses.SD_INSERT_DONE_X and not _uses_approach(layer):
        log(f'[load2] 작업대 {layer}층 넣기 좌표 없음 -> 작업대 앞에서 멈춤')
        return True
    ok = insert_sd(layer, log=log)   # 밀기 끝나면 항상 그리퍼를 연다 (완료 확인 여부는 ok)
    if not ok:
        log('[load2] 넣기 완료 확인 안 됨 (위치/반력) -> 그래도 그리퍼 열었으니 빼고 홈으로. 결과 False')
    retreat_sd(layer, log=log)
    if _uses_quick_retreat(layer):
        pass   # 짧게 빼고 바로 홈
    elif _uses_approach(layer):
        pass   # retreat_sd가 sd 3까지 나옴
    elif layer in poses.SD_POS_J:
        movej(posj(*poses.SD_POS_J[layer]), vel=EMPTY_VELJ, acc=EMPTY_ACCJ)
    else:
        _movel_checked(poses.SD_POS_X[layer], fast=True)
    if layer != poses.SD_TOP_LAYER and not _uses_approach(layer) and not _uses_quick_retreat(layer):
        movej(posj(*poses.SD_POS_J[poses.SD_TOP_LAYER]), vel=EMPTY_VELJ, acc=EMPTY_ACCJ)
    log('[load2] 홈 이동 (빈손 속도)')
    go_home(fast=True)
    return ok


# ---- 2-2. Load1: 홈 -> 적재대 -> 잡기 -> 판재 확인 (숙여 누르기) -> 없으면 내려놓고 홈


def _load1_common(goal, name: str, log=print) -> bool:
    """홈 -> 적재대 layer층 -> 잡고 판재 확인.

    있으면 True (들어 올린 채 멈춤, 다음 load2가 여기서 시작) / 없으면 내려놓고 홈 -> False.
    """
    layer = goal.start_pos_id
    log(f'[{name}] 적재대 {layer}층')
    home_to_board(layer)
    if grip_and_check(poses.START_POS_PICK_X[layer], log=log, layer=layer):
        return True
    log(f'[{name}] 판재 없음 (숙여 누르기 확인) -> 판재 내려놓고 홈으로 (결과 False)')
    put_back_and_home(layer, log=log)
    return False


def home_to_board(layer: int = 3, until: int | None = None, before_step=None) -> None:
    """홈(그리퍼 열기) -> 준비 -> 진입 높이 -> 진입 전 -> 적재대 layer층.

    until: 이 단계까지만 (0홈 1준비 2진입높이 3진입전 4적재대). before_step(번호, 이름)이 False면 거기서 멈춤.
    """
    for table, name in ((poses.START_POS_READY_J, 'START_POS_READY'),
                        (poses.START_POS_APPROACH_X, 'START_POS_APPROACH'),
                        (poses.START_POS_PICK_X, 'START_POS_PICK')):
        if layer not in table:
            raise ValueError(f'{name}에 {layer}층 좌표 없음 (가능: {list(table)})')

    steps = [
        # 홈 -> 진입 전까지는 빈손이라 빠르게 (fast). 잡는 곳으로 들어가는 마지막만 기본 속도.
        ('홈 (그리퍼 열기)', lambda: (go_home(fast=True), grip_open())),  # 홈은 항상 movej
        (f'적재대 {layer}층 준비', lambda: go_ready(layer, fast=True)),  # 준비도 항상 movej
        (f'진입 높이 (적재대 {poses.ENTRY_LAYER}층 진입 전 높이)', lambda: go_entry_top(layer, fast=True)),
        (f'적재대 {layer}층 진입 전 (Z로 수직 하강)',
         lambda: _move_to(poses.START_POS_APPROACH_J.get(layer), poses.START_POS_APPROACH_X[layer], fast=True)),
        (f'적재대 {layer}층',
         lambda: _move_to(poses.START_POS_PICK_J.get(layer), poses.START_POS_PICK_X[layer])),
    ]
    for i, (name, move) in enumerate(steps):
        if until is not None and i > until:
            return
        if before_step is not None and before_step(i, name) is False:
            raise MotionStopped(f'{i}단계({name}) 전에 멈춤')
        move()


def go_ready(layer: int, fast: bool = False) -> None:
    """layer층 준비 위치로 movej (홈과 손목 자세가 크게 달라 movel이면 J5 특이점을 지남)."""
    v, a = (EMPTY_VELJ, EMPTY_ACCJ) if fast else (VELJ, ACCJ)
    movej(posj(*poses.START_POS_READY_J[layer]), vel=v, acc=a)


def go_entry_top(layer: int, fast: bool = False) -> None:
    """layer층 진입 전 X, Y로 공통 진입 높이에서 직선 이동 (여기서 Z로만 내리면 진입 전)."""
    top = list(poses.START_POS_APPROACH_X[layer])
    top[2] = poses.START_POS_APPROACH_X[poses.ENTRY_LAYER][2]
    _movel_checked(top, fast=fast)


def grip_and_check(pose_x: list, log=print, layer: int | None = None) -> bool:
    """잡고 LIFT_Z_MM 들어 올린 뒤 ry로 숙여 눌러서 판재가 있는지 확인 -> 원래 자세로.

    판재가 가벼워 무게로는 구분이 안 돼서, 숙인 뒤 Fz가 기준보다 크면(판재 끝이 선반을 누름) True.
    각도/기준은 poses.TILT_CHECK_DEG_BY_LAYER / TILT_CHECK_FZ_BY_LAYER, 없으면 TILT_CHECK_DEG / TILT_CHECK_FZ_N.
    """
    deg = getattr(poses, 'TILT_CHECK_DEG_BY_LAYER', {}).get(layer, TILT_CHECK_DEG)
    fz_n = getattr(poses, 'TILT_CHECK_FZ_BY_LAYER', {}).get(layer, TILT_CHECK_FZ_N)
    grip_close()
    lifted = list(pose_x)
    lifted[2] += LIFT_Z_MM
    _movel_checked(lifted, vel=CARRY_VELX)   # 판재 들기
    wait(TILT_CHECK_SETTLE_SEC)
    fz0 = read_force_xyz(TILT_CHECK_SAMPLES)[2]
    tilt_base('y', deg, log=log, check=False)
    wait(TILT_CHECK_SETTLE_SEC)
    fz1 = read_force_xyz(TILT_CHECK_SAMPLES)[2]
    tilt_base('y', -deg, log=log, check=False)
    picked = fz1 > fz_n
    log(f'[판재 확인] {layer if layer is not None else "?"}층 ry +{deg:g}도 숙여 누르기: 전 Fz={fz0:.2f}N  숙인 뒤 Fz={fz1:.2f}N '
        f'(차이 {fz1 - fz0:+.2f}N)  기준: 숙인 뒤 Fz > {fz_n}N  -> {"판재 있음" if picked else "판재 없음"}')
    return picked


PUT_BACK_RETREAT_MM = 100.0   # 판재 내려놓고 그리퍼 연 뒤 -X로 빠지는 거리 (mm), 그다음 바로 홈


def put_back_and_home(layer: int, log=print) -> None:
    """판재를 제자리에 내려놓기 -> 그리퍼 열기 -> -X로 PUT_BACK_RETREAT_MM -> 홈 (빈손 속도)."""
    log(f'[내려놓기] 적재대 {layer}층: 제자리로 내리기 -> 그리퍼 열기 -> 뒤로 {PUT_BACK_RETREAT_MM:.0f}mm -> 홈')
    pick = list(poses.START_POS_PICK_X[layer])
    _movel_slow(pick, '잡는 곳(내려놓기)')
    grip_open()
    wait(SETTLE_SEC)
    back = list(pick)
    back[0] -= PUT_BACK_RETREAT_MM
    _movel_checked(back)   # 판재 옆을 지나가므로 기본 속도(VELX)
    go_home(fast=True)
    log('[내려놓기] 홈 도착 (빈손)')


def pull_out(dist: float = PULL_OUT_MM, log=print) -> None:
    """높이, Y, 자세 그대로 -X로 dist mm 빼기 (층별 빼기 순서가 없는 층의 기본 동작). 못 가면 예외.

    가상 로봇 확인 가능 거리: 3층 230mm, 2층 150mm, 1층 100mm.
    """
    cur = list(get_current_posx()[0])
    target = list(cur)
    target[0] -= dist
    log(f'[빼기] X {cur[0]:.1f} -> {target[0]:.1f} (-{dist:.0f}mm), Y {cur[1]:.1f}, Z {cur[2]:.1f} 유지')
    _movel_checked(target, vel=CARRY_VELX)


def rise_to_top(log=print) -> None:
    """X, Y, 자세 그대로 3층 들어 올린 높이까지 Z로만 올라가기 (이미 그 이상이면 안 움직임)."""
    top_z = poses.START_POS_PICK_X[poses.ENTRY_LAYER][2] + LIFT_Z_MM
    cur = list(get_current_posx()[0])
    if cur[2] >= top_z - REACH_TOL_MM:
        log(f'[올리기] 지금 Z {cur[2]:.1f} >= 3층 높이 {top_z:.1f} -> 안 움직임')
        return
    target = list(cur)
    target[2] = top_z
    log(f'[올리기] Z {cur[2]:.1f} -> {top_z:.1f} (3층 높이, X {cur[0]:.1f} Y {cur[1]:.1f} 그대로)')
    _movel_checked(target, vel=CARRY_VELX)


# ---- 2-3. Load2 (1) 적재대에서 빼기 (층별 순서 RACK_EXIT_STEPS)


def rack_layer_now() -> int | None:
    """지금 위치가 적재대 몇 층에서 잡고 들어 올린 높이인지 (적재대 쪽 +Y이고 높이가 맞을 때). 모르면 None."""
    cur = list(get_current_posx()[0])
    rack_y = min(x[1] for x in poses.START_POS_PICK_X.values()) - 100.0
    if cur[1] <= rack_y:
        return None
    best = min(poses.START_POS_PICK_X,
               key=lambda n: abs(cur[2] - (poses.START_POS_PICK_X[n][2] + LIFT_Z_MM)))
    if abs(cur[2] - (poses.START_POS_PICK_X[best][2] + LIFT_Z_MM)) > poses.RACK_LAYER_Z_TOL_MM:
        return None
    return best


def exit_rack(layer: int | None = None, log=print) -> bool:
    """(load1로 들어 올린 뒤) 적재대에서 빼기.

    layer가 None이면 지금 높이로 층을 알아냄. RACK_EXIT_STEPS에 순서가 있으면 그대로, 없으면 pull_out -> rise_to_top.
    반환: 층별 순서로 뺐으면 True, 기본 동작이면 False.
    """
    if layer is None:
        layer = rack_layer_now()
        if layer is None:
            # 적재대에서 잡고 든 위치가 아니면 어디로 뺄지 모름 -> 움직이지 않고 실패
            cur = list(get_current_posx()[0])
            raise RuntimeError(f'적재대에서 잡고 든 위치가 아님 (지금 {[round(v, 1) for v in cur[:3]]}) -> 빼기 안 함. '
                               f'load1 먼저 할 것')
    steps = poses.RACK_EXIT_STEPS.get(layer)
    if not steps:
        log(f'[적재대 빼기] {layer}층: 기본 동작 (-X {PULL_OUT_MM:.0f}mm -> 3층 높이로 올리기)')
        pull_out(log=log)
        rise_to_top(log=log)
        return False
    log(f'[적재대 빼기] {layer}층 순서 {len(steps)}단계: {steps}')
    for i, (kind, val) in enumerate(steps, 1):
        log(f' {i}/{len(steps)} {kind} {val:+g}')
        # 적재대 빼기는 도착 확인으로 멈추지 않음 (실제 로봇에서 끝 위치가 몇 mm 어긋나도 그냥 계속)
        if kind == 'x':
            move_rel(dx=val, log=log, check=False, vel=CARRY_VELX)
        elif kind == 'y':
            move_rel(dy=val, log=log, check=False, vel=CARRY_VELX)
        elif kind == 'z':
            move_rel(dz=val, log=log, check=False, vel=CARRY_VELX)
        elif kind in ('rx', 'ry', 'rz'):
            tilt_base(kind[1], val, log=log, check=False)
        else:
            raise ValueError(f'RACK_EXIT_STEPS 단계 종류를 모름: {kind} (x / y / z / ry)')
    cur = list(get_current_posx()[0])
    log(f'[적재대 빼기] 끝: {[round(v, 1) for v in cur]}')
    return True


# ---- 2-4. Load2 (2) 작업대 sd 위치로 이동


def _check_sd_layer(layer: int) -> None:
    if layer not in poses.SD_POS_X:
        raise ValueError(f'SD_POS에 {layer}층 좌표 없음 (가능: {list(poses.SD_POS_X)})')


def go_sd(layer: int = 3, log=print, force: bool = False) -> None:
    """(판재 든 채) 작업대 sd 3으로 movej -> 다가가기 층이 아니면 movel로 layer층까지 내려감.

    force는 안 씀 (예전 적재대 안전 확인용, 2026-11-19에 뺌).
    """
    _check_sd_layer(layer)
    cur = list(get_current_posx()[0])

    top = poses.SD_TOP_LAYER
    log(f'[작업대] 지금 {[round(v, 1) for v in cur[:3]]} -> 작업대 {top}층 {poses.SD_POS_X[top][:3]} (movej)')
    movej(posj(*poses.SD_POS_J[top]), vel=CARRY_VELJ, acc=CARRY_ACCJ)   # 판재 든 채
    j = list(get_current_posj())
    err = max(abs(j[i] - poses.SD_POS_J[top][i]) for i in range(6))
    if err > 1.0:
        raise RuntimeError(
            f'작업대 {top}층에 못 감: 목표 J={poses.SD_POS_J[top]} 현재 J={[round(v, 1) for v in j]}')

    if layer != top and _uses_approach(layer):
        log(f'[작업대] {layer}층은 insert에서 sd 3부터 다가가기 순서로 내려감 -> 여기서 멈춤')
    elif layer != top:
        log(f'[작업대] {top}층 -> {layer}층 {poses.SD_POS_X[layer][:3]} (movel 하강)')
        _movel_checked(poses.SD_POS_X[layer], vel=CARRY_VELX)


# ---- 2-5. Load2 (3) 넣기 - insert_sd가 층별 설정(poses)에 따라 방식 선택


def insert_sd(layer: int = 3, log=print, keep_ori: bool = False, from_entrance: bool = False) -> bool:
    """작업대 layer층에 판재 넣기. 밀기가 끝나면 항상 그리퍼를 열고, 완료(위치 + 반력)를 확인했으면 True.

    층별 방식 (poses 설정):
      SD_INSERT_CHECK_ONLY (1층): 다가가기 -> 마지막 fwd를 위치 + 순응 제어로 밀며 반력 확인
      SD_INSERT_APPROACH   (2층): sd 3에서 다가가기 -> 입구 -> SD_INSERT_DONE_X까지 직선 -> 순응 밀기
      기본                 (3층): 첫 점 -> 입구 -> 끝까지 직선 -> 순응 밀기
    순응 밀기: 끝 PUSH_START_BEFORE_MM 앞부터 PUSH_STEP_MM씩, 위치 도착 그리고 반력 > 기준이면 완료.
    from_entrance=True: (motion_test inpush) 이미 입구에 있음 -> 다가가기 건너뜀. keep_ori는 안 씀.
    위치 이동 중 힘이 JAM_FORCE_N 넘으면 예외 (잡은 채로 멈춤).
    """
    if getattr(poses, 'SD_INSERT_CHECK_ONLY', {}).get(layer):
        if from_entrance:
            raise ValueError(f'{layer}층은 마지막 fwd에서 힘을 확인하는 방식이라 입구부터 넣기(inpush)를 못 씀 -> insert {layer}')
        return _check_force_and_release(layer, log=log)
    front, done, u, length = _insert_line(layer)
    pre = _insert_pre(layer)
    log(f'[넣기] 첫 점 {[round(v, 1) for v in pre[:3]]} -> 입구 {[round(v, 1) for v in front[:3]]} -> 끝 {[round(v, 1) for v in done[:3]]} '
        f'(직선 {length:.1f}mm, 방향 {[round(v, 3) for v in u]})')
    if keep_ori:
        log('[넣기] (sd 축정렬 자세 대신 측정한 자세를 씀)')

    if from_entrance:
        # (motion_test inpush) 이미 enter로 다가가기 끝(입구)에 와 있음 -> 다가가기 건너뜀
        cur = list(get_current_posx()[0])
        err = max(abs(cur[i] - pre[i]) for i in range(3))
        log(f'[넣기] 입구부터 넣기: 지금 {[round(v, 1) for v in cur[:3]]} (입구와 차이 {err:.1f}mm)')
        if err > 20.0:
            raise RuntimeError(f'입구에서 너무 멂 (차이 {err:.1f}mm). enter {layer} 먼저 할 것')
    elif _uses_approach(layer):
        approach_sd(layer, log=log)   # sd 3에서 다가가기 순서대로 (마지막 점 = 입구 전 대기 위치)
    else:
        _movel_checked(pre, vel=INSERT_VELX)
    log(f'[넣기] {PRE_INSERT_HOLD_SEC}초 멈춤')
    wait(PRE_INSERT_HOLD_SEC)
    log(f'[넣기] 입구 {[round(v, 1) for v in front[:3]]} 자세 {[round(v, 2) for v in front[3:6]]}')
    _movel_checked(front, vel=INSERT_VELX)
    wait(SETTLE_SEC)
    base = read_force_xyz()
    log(f'[넣기] 기준 힘 Fx={base[0]:.1f} Fy={base[1]:.1f} Fz={base[2]:.1f}N')

    # 직선으로 끝 PUSH_START_BEFORE_MM 앞까지
    s0 = length - getattr(poses, 'SD_PUSH_START_BEFORE_MM', {}).get(layer, PUSH_START_BEFORE_MM)
    _insert_move(_point_on_line(front, done, s0), base, log, '일자로 넣기',
                 vel=STRAIGHT_VELX, acc=STRAIGHT_ACCX)
    s_max = length + getattr(poses, 'SD_PUSH_OVERSHOOT_MM', {}).get(layer, PUSH_OVERSHOOT_MM)

    # 순응 제어로 같은 직선 방향으로 밀면서 끝 위치 + 반력 확인
    wait(SETTLE_SEC)
    base = read_force_xyz()
    react_n = getattr(poses, 'SD_DONE_REACT_N', {}).get(layer, DONE_REACT_N)   # 층별 반력 기준
    cond = f'진행 >= {length - DONE_POS_TOL_MM:.1f}mm 그리고 반력 > {react_n}N'
    log(f'[넣기] 순응 제어로 밀기: 직선 {s0:.1f} -> 최대 {s_max:.1f}mm, {PUSH_STEP_MM:.0f}mm씩 (완료: {cond})')
    # X 강성: 끝에 막힌 채 목표가 끝 + PUSH_OVERSHOOT_MM이면 PUSH_FORCE_N으로 누르게
    stx = list(COMPLIANCE_STX)
    stx[0] = PUSH_FORCE_N / (PUSH_OVERSHOOT_MM / 1000.0)
    log(f'[넣기] 순응 강성 X {stx[0]:.0f}N/m ({stx[0] / 1000:.2f}N/mm, 끝 +{PUSH_OVERSHOOT_MM:.0f}mm에서 약 {PUSH_FORCE_N}N)')
    finished = False
    max_react, max_at, last_f = -1e9, 0.0, [0.0, 0.0, 0.0]   # 힘 요약용
    if _keep_z(layer):
        # 높이 고정: Z 강성 최대 (밀 때 내려앉지 않게)
        stx[2] = KEEP_Z_STIFF_N_M
        log(f'[넣기] 높이 고정 순응 제어: 강성 {[round(v) for v in stx[:3]]}N/m (X만 무름, Z 고정)')
    task_compliance_ctrl(stx=stx)
    try:
        wait(0.3)
        st = s0
        while st < s_max - 1e-9:
            st = min(st + PUSH_STEP_MM, s_max)
            movel(posx(*_point_on_line(front, done, st)), vel=PUSH_VELX, acc=PUSH_ACCX)
            f = read_force_xyz(PUSH_FORCE_SAMPLES)
            cur = list(get_current_posx()[0])
            s_now = sum((cur[i] - front[i]) * u[i] for i in range(3))   # 직선 위 진행 거리
            lag = st - s_now
            react = -sum((f[i] - base[i]) * u[i] for i in range(3))     # 미는 방향 반력 (+ = 밀림)
            last_f = [f[i] - base[i] for i in range(3)]
            if react > max_react:
                max_react, max_at = react, st
            reached = s_now >= length - DONE_POS_TOL_MM
            force_ok = react > react_n   # 기준 초과 (기준 0N이면 반력이 양수가 되는 순간)
            msg = (f'  [밀기 {st:.1f}mm] 진행 {s_now:.1f}mm (끝까지 {length - s_now:+.1f}mm, 덜 감 {lag:.1f}mm) '
                   f'반력 {react:+.2f}N  Fx={f[0]:+.2f} Fy={f[1]:+.2f} Fz={f[2]:+.2f}  '
                   f'위치{"O" if reached else "X"} 힘{"O" if force_ok else "X"}')
            if reached and force_ok:
                log(msg + '  -> 넣기 완료')
                finished = True
                break
            log(msg)
        else:
            log('[넣기] 끝까지 밀었는데 완료 아님')
    finally:
        # 순응 해제 먼저 (그리퍼 열 때 눌려 있던 힘으로 손목이 튀지 않게)
        release_compliance_ctrl()
    log(f'[넣기] 힘 요약: 최대 반력 {max_react:+.2f}N ({max_at:.0f}mm에서), 마지막 힘 변화 '
        f'dFx={last_f[0]:+.2f} dFy={last_f[1]:+.2f} dFz={last_f[2]:+.2f}N (기준 반력 {react_n}N)')
    # 밀기가 끝나면 완료 여부와 상관없이 항상 그리퍼 열기 (순응 해제 뒤)
    grip_open()
    if finished:
        log('[넣기] 그리퍼 열기 (판재 놓음)')
    else:
        log('[넣기] 완료 확인은 안 됐지만 그리퍼 열기 (판재 놓음) -> 결과 False')
    return finished


def _uses_approach(layer: int) -> bool:
    """이 층은 sd 3에서 다가가기 순서(SD_INSERT_APPROACH)로 입구까지 가는지."""
    return layer in getattr(poses, 'SD_INSERT_APPROACH', {})


def _approach_points(layer: int) -> list:
    """sd 3에서 SD_INSERT_APPROACH[layer] 순서대로 간 점들 (마지막 = 입구). 자세는 rx/ry/rz 단계에서만 바뀜."""
    p = list(poses.SD_POS_X[poses.SD_TOP_LAYER])
    pts = []
    for kind, val in poses.SD_INSERT_APPROACH[layer]:
        if kind == 'fwd':
            d = _tool_z_dir(p[3:6])
            for i in range(3):
                p[i] += d[i] * val
        elif kind in ('x', 'y', 'z'):
            p['xyz'.index(kind)] += val
        elif kind in ('rx', 'ry', 'rz'):
            p = p[:3] + rotate_about_base(kind[1], p[3:6], val)
        else:
            raise ValueError(f'SD_INSERT_APPROACH 단계 종류를 모름: {kind} (fwd / x / y / z / rx / ry / rz)')
        pts.append(list(p))
    return pts


def approach_sd(layer: int, log=print, skip_last: bool = False) -> None:
    """sd 3 -> 다가가기 순서 끝(입구)까지. insert_sd 앞부분이고 motion_test enter에서도 씀. 그리퍼 그대로."""
    if not _uses_approach(layer):
        raise ValueError(f'{layer}층은 다가가기 순서(SD_INSERT_APPROACH)가 없음 (가능: {list(poses.SD_INSERT_APPROACH)})')
    pts = _approach_points(layer)
    log(f'[넣기] {layer}층: sd 3에서 다가가기 {poses.SD_INSERT_APPROACH[layer]}')
    _movel_slow(poses.SD_POS_X[poses.SD_TOP_LAYER], 'sd 3')
    steps = poses.SD_INSERT_APPROACH[layer]
    rot = ('rx', 'ry', 'rz')
    for i, ((kind, val), pt) in enumerate(zip(steps, pts), 1):
        if skip_last and i == len(steps):
            break   # 마지막 단계는 부르는 쪽(_check_force_and_release)이 힘 재면서 직접 함
        if kind in rot and i < len(steps) and steps[i][0] in rot:
            log(f'  {i}/{len(pts)} {kind} {val:+g} (다음 회전과 같이)')
            continue   # 이어지는 회전 단계는 모아서 마지막 점으로 한 번에 돌림
        log(f'  {i}/{len(pts)} {kind} {val:+g} -> {[round(v, 1) for v in pt[:3]]}'
            + (f' 자세 {[round(v, 2) for v in pt[3:6]]}' if kind in rot else ''))
        _movel_slow(pt, f'다가가기 {i}단계', rotate=kind in rot)


CHECK_STEP_MM = 5.0   # SD_INSERT_CHECK_ONLY 층: 마지막 fwd를 이만큼씩 나눠 가며 매번 힘 확인


def _check_force_and_release(layer: int, log=print) -> bool:
    """(SD_INSERT_CHECK_ONLY 층) 마지막 fwd를 밀며 반력 확인 -> 항상 그리퍼 열기, 항상 True.

    처음 SD_INSERT_CHECK_FROM_MM은 위치 제어, 나머지는 순응 제어로 CHECK_STEP_MM씩 밀며 반력 > SD_DONE_REACT_N이면 멈춤.
    """
    approach_sd(layer, log=log, skip_last=True)
    steps, pts = poses.SD_INSERT_APPROACH[layer], _approach_points(layer)
    start, last = pts[-2], pts[-1]
    kind, val = steps[-1]
    total = math.sqrt(sum((last[i] - start[i]) ** 2 for i in range(3)))
    u = _push_dir(layer, last[3:6])
    react_n = getattr(poses, 'SD_DONE_REACT_N', {}).get(layer, DONE_REACT_N)
    free = min(getattr(poses, 'SD_INSERT_CHECK_FROM_MM', {}).get(layer, 0.0), total)

    def at(d: float) -> list:
        t = d / total
        return [start[i] + (last[i] - start[i]) * t for i in range(6)]

    log(f'  {len(steps)}/{len(steps)} {kind} {val:+g} -> {[round(v, 1) for v in last[:3]]} '
        f'(처음 {free:.0f}mm 위치 제어, 나머지 {total - free:.0f}mm 순응 제어 {CHECK_STEP_MM:.0f}mm씩, '
        f'반력 > {react_n}N이면 멈추고 놓기)')
    d = 0.0
    if free > 0:
        movel(posx(*at(free)), vel=INSERT_VELX, acc=INSERT_ACCX)
        d = free
        log(f'  [밀기 {d:.0f}/{total:.0f}mm] 위치 제어로 이동')
    wait(SETTLE_SEC)
    base = read_force_xyz()
    stx = list(COMPLIANCE_STX)
    stx[0] = PUSH_FORCE_N / (PUSH_OVERSHOOT_MM / 1000.0)
    if _keep_z(layer):
        stx[2] = KEEP_Z_STIFF_N_M   # 높이 고정
    log(f'[넣기] 순응 제어 켜기: 강성 {[round(v) for v in stx[:3]]}N/m')
    got = False
    task_compliance_ctrl(stx=stx)
    try:
        wait(0.3)
        while d < total - 1e-9:
            d = min(d + CHECK_STEP_MM, total)
            movel(posx(*at(d)), vel=PUSH_VELX, acc=PUSH_ACCX)
            f = read_force_xyz(PUSH_FORCE_SAMPLES)
            react = -sum((f[i] - base[i]) * u[i] for i in range(3))
            got = react > react_n   # 기준 초과 (0N이면 양수가 되는 순간)
            log(f'  [순응 밀기 {d:.0f}/{total:.0f}mm] 반력 {react:+.2f}N (기준 > {react_n}N)'
                f'{" -> 받음, 멈추고 놓기" if got else ""}')
            if got:
                break
    finally:
        release_compliance_ctrl()   # 그리퍼 열기 전에 순응 해제 (손목 튐 방지)
    if not got:
        log(f'[넣기] {total:.0f}mm 끝까지 밀었는데 반력 {react_n}N 안 받음 -> 그대로 놓음')
    grip_open()
    log('[넣기] 그리퍼 열기 (판재 놓음)')
    return True


KEEP_Z_STIFF_N_M = 20000.0   # SD_INSERT_KEEP_Z 층: 밀 때 Z(위아래) 강성 (N/m, 순응 제어 최대값) -> 높이 고정


def _keep_z(layer: int) -> bool:
    return bool(getattr(poses, 'SD_INSERT_KEEP_Z', {}).get(layer))


def _push_dir(layer: int, ori: list) -> list:
    """미는 방향 단위벡터. SD_INSERT_KEEP_Z 층은 미는 축을 수평(XY)으로 눕힌 방향 (높이 유지)."""
    d = _tool_z_dir(ori)
    if _keep_z(layer):
        n = math.hypot(d[0], d[1])
        d = [d[0] / n, d[1] / n, 0.0]
    return d


def _insert_pre(layer: int) -> list:
    """넣기 첫 점 (여기서 PRE_INSERT_HOLD_SEC 멈춤). 다가가기 방식이면 입구."""
    if _uses_approach(layer):
        return _approach_points(layer)[-1]
    return list(poses.SD_PRE_INSERT_X[layer])


def _insert_line(layer: int) -> tuple[list, list, list, float]:
    """넣는 직선 (입구, 끝, 방향 단위벡터, 길이 mm)."""
    if _uses_approach(layer):
        if layer not in poses.SD_INSERT_DONE_X:
            raise ValueError(f'{layer}층: SD_INSERT_DONE_X 없음')
        front = _approach_points(layer)[-1]
        done = list(poses.SD_INSERT_DONE_X[layer])
    else:
        for table, name in ((poses.SD_PRE_INSERT_X, 'SD_PRE_INSERT'),
                            (poses.SD_INSERT_FRONT_X, 'SD_INSERT_FRONT'),
                            (poses.SD_INSERT_DONE_X, 'SD_INSERT_DONE')):
            if layer not in table:
                raise ValueError(f'{name}에 {layer}층 좌표 없음 (가능: {list(table)})')
        front = list(poses.SD_INSERT_FRONT_X[layer])
        done = list(poses.SD_INSERT_DONE_X[layer])
    vec = [done[i] - front[i] for i in range(3)]
    length = math.sqrt(sum(v * v for v in vec))
    return front, done, [v / length for v in vec], length


def _point_on_line(front: list, done: list, d: float) -> list:
    """입구에서 직선 따라 d(mm) 간 점. 자세는 입구~끝 비율로 보간, 끝을 넘으면 끝 자세."""
    length = math.sqrt(sum((done[i] - front[i]) ** 2 for i in range(3)))
    t = d / length
    p = [front[i] + (done[i] - front[i]) * t for i in range(3)]
    tt = min(max(t, 0.0), 1.0)
    return p + [front[i] + (done[i] - front[i]) * tt for i in range(3, 6)]


def _insert_move(pose_x: list, base: list, log, label: str,
                 vel: float = INSERT_VELX, acc: float = INSERT_ACCX,
                 jam: float = JAM_FORCE_N, samples: int = FORCE_SAMPLES) -> None:
    """느린 movel + 이동 후 X/Y 힘 변화 확인. jam(N) 이상이면 걸린 것으로 보고 멈춤 (놓지 않음)."""
    movel(posx(*pose_x), vel=vel, acc=acc)
    f = read_force_xyz(samples)
    dfx, dfy = f[0] - base[0], f[1] - base[1]
    log(f'  [{label}] X={pose_x[0]:.1f} Y={pose_x[1]:.1f}  dFx={dfx:+.1f}N dFy={dfy:+.1f}N')
    if max(abs(dfx), abs(dfy)) >= jam:
        raise RuntimeError(f'넣다가 걸림 ({label}: dFx={dfx:+.1f}N dFy={dfy:+.1f}N, '
                           f'기준 {jam}N) -> 멈춤, 그리퍼는 잡은 상태')


def align_push_axis(log=print) -> list:
    """툴 Z축(미는 방향)을 ALIGN_VECT(+X)에 맞추고 자세 [A,B,C] 반환. ALIGN_MAX_DEG보다 많이 다르면 안 움직이고 예외."""
    cur = list(get_current_posx()[0])
    z = _tool_z_dir(cur[3:6])
    n = math.sqrt(sum(v * v for v in ALIGN_VECT))
    cosang = sum(z[i] * ALIGN_VECT[i] for i in range(3)) / n
    ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
    log(f'[축정렬] 지금 툴 Z축 {[round(v, 3) for v in z]}, 미는 방향 {ALIGN_VECT}과 {ang:.1f}도 차이')
    if ang > ALIGN_MAX_DEG:
        raise RuntimeError(f'축정렬 각도가 너무 큼 ({ang:.1f}도 > {ALIGN_MAX_DEG}도) -> 정렬 안 하고 멈춤')
    align_axis(vect=list(ALIGN_VECT), pos=posx(*cur), axis=DR_AXIS_Z, ref=DR_BASE)
    new = list(get_current_posx()[0])
    log(f'[축정렬] 자세 {[round(v, 2) for v in cur[3:6]]} -> {[round(v, 2) for v in new[3:6]]}, '
        f'위치 {[round(v, 1) for v in new[:3]]}')
    return new[3:6]


# ---- 2-6. Load2 (4) 놓은 뒤 빼기 -> 홈


def retreat_sd(layer: int = 3, log=print) -> None:
    """(놓은 뒤) 빼기. SD_RETREAT_STEPS 층은 짧게(_quick_retreat), 아니면 넣은 길 거꾸로. 그리퍼 그대로."""
    if _uses_quick_retreat(layer):
        _quick_retreat(layer, log=log)
        return
    front, done, _, _ = _insert_line(layer)
    pre = _insert_pre(layer)
    cur = list(get_current_posx()[0])
    log(f'[빼기] 지금 {[round(v, 1) for v in cur[:3]]} -> 입구 {[round(v, 1) for v in front[:3]]} -> 첫 점 {[round(v, 1) for v in pre[:3]]} (그리퍼 그대로)')
    route = [('입구', front), ('첫 점', pre)]
    if _uses_approach(layer):
        # 다가가기 길을 거꾸로 -> sd 3
        pts = _approach_points(layer)
        steps = poses.SD_INSERT_APPROACH[layer]
        rot = ('rx', 'ry', 'rz')
        # 거꾸로 갈 때도 이어지는 회전 단계는 한 번에 (회전 묶음의 앞 단계 점들은 건너뜀)
        back = [i for i in range(len(pts) - 1, 0, -1)
                if not (steps[i][0] in rot and steps[i - 1][0] in rot)]
        route = [('입구', front)] + [(f'다가가기 {i}단계', pts[i - 1]) for i in back] \
            + [('sd 3', list(poses.SD_POS_X[poses.SD_TOP_LAYER]))]
    prev = list(get_current_posx()[0])
    for name, target in route:
        # 자세만 바뀌는 구간(다가가기의 회전 단계를 되돌릴 때)은 천천히 돌리고 잠깐 멈춤
        rotate = max(abs(target[i] - prev[i]) for i in range(3)) < 1.0 and \
            max(abs(target[i] - prev[i]) for i in range(3, 6)) > 0.05
        try:
            _movel_slow(target, name, rotate=rotate)
        except RuntimeError as exc:
            raise RuntimeError(f'빼기 중 {exc}') from exc
        prev = list(target)
    log(f'[빼기] {route[-1][0]} 도착')


def _uses_quick_retreat(layer: int) -> bool:
    return layer in getattr(poses, 'SD_RETREAT_STEPS', {})


def _quick_retreat(layer: int, log=print) -> None:
    """SD_RETREAT_STEPS[layer] 순서로 빼기. 그리퍼 그대로.

    ('x'/'y'/'z', mm) = 지금 자세 그대로 직선 (QUICK_RETREAT_VELX) / ('entrance', 0) = 넣은 직선 따라 입구까지 (INSERT_VELX).
    """
    steps = poses.SD_RETREAT_STEPS[layer]
    log(f'[빼기] {layer}층 빠른 빼기 {steps} -> 홈')
    for i, (kind, val) in enumerate(steps, 1):
        if kind == 'entrance':
            front = _insert_line(layer)[0]
            log(f'  {i}/{len(steps)} 입구까지 {[round(v, 1) for v in front[:3]]}')
            _movel_slow(front, '입구')
        elif kind in ('x', 'y', 'z'):
            d = {'x': 0.0, 'y': 0.0, 'z': 0.0}
            d[kind] = val
            log(f'  {i}/{len(steps)} {kind} {val:+g}')
            move_rel(dx=d['x'], dy=d['y'], dz=d['z'], log=log, vel=QUICK_RETREAT_VELX)
        else:
            raise ValueError(f'SD_RETREAT_STEPS 단계 종류를 모름: {kind} (x / y / z / entrance)')


# ============================================================================
# PART 3. Unload - 작업대에서 판재 꺼내기  (※ 다른 사람 작업)
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
    4) UNLOAD_RETURN_J 순서로 홈 복귀
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

    return_steps = list(getattr(unload_poses, 'UNLOAD_RETURN_J', []))
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

    log(f'  수령대{receive_pos_id} 도착 -> 그리퍼 열기 (놓기)')
    grip_open()

    for name, jj in return_steps:
        unload_move_j(name, jj, log=log)

    log(f'[unload2] 수령대{receive_pos_id} 전달 후 홈 복귀 완료')
    return True


def run_unload(goal: Unload.Goal, log=print) -> bool:
    """Unload: 아직 동작 없음. 홈 위치로만 이동."""
    go_home()
    return True


# ---- 3-2. 언로드 이동 / 잡고 당기기


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
# PART 4. 조그 / 그리퍼  (※ 다른 사람 작업 - 티칭 팬던트)
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
