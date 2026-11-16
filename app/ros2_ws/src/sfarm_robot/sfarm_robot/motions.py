"""
로봇 구체 동작 (Load / Unload).

robot_action_server.py가 goal을 받으면 여기의 run_load() / run_unload()를 호출한다.
  - 함수가 True(또는 None)를 돌려주면 -> 작업 성공 (success=True)
  - 함수가 False를 돌려주면           -> 작업 실패 (success=False, 예: 무게 감지 안 됨)
  - 함수 안에서 예외가 나면           -> 작업 실패 (success=False, message에 예외 내용)

Load 동작 흐름
  run_load()                 층 = goal.start_pos_id (1, 2, 3)
   ├─ home_to_board(층)      홈(그리퍼 열기) -> 준비 -> 진입 높이 -> (Z로 수직 하강) 진입 전 -> 적재대
   └─ grip_and_check()       Fz(전) -> 그리퍼 닫기 -> +Z 들기 -> Fz(후) -> True/False
                             (들어 올린 상태로 끝)

주의: 이 파일은 DSR_ROBOT2를 맨 위에서 import 하므로, robot_action_server.py의
main()이 DR_init 설정(로봇 ID, 모델, 노드)을 끝낸 뒤에 import 된다.
이 파일을 단독으로 import 하거나 실행하면 안 된다.
"""
from __future__ import annotations

from DR_common2 import posj, posx
import math

from DSR_ROBOT2 import (
    DR_AXIS_Z,
    DR_BASE,
    OFF,
    ON,
    align_axis,
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

from sfarm_interfaces.action import Load, Load1, Load2, Unload, Unload1

from . import poses

# ---------------------------------------------------------------- 속도
VELJ, ACCJ = 30.0, 30.0      # 관절 이동 (movej)
VELX, ACCX = 100.0, 100.0    # 직선 이동 (movel)

# 준비(1단계) -> 진입 전 -> 적재대 이동 방식 (홈, 준비 위치는 항상 movej)
#   True : movel (posx, 직선 이동)
#   False: movej (posj, 관절 이동) - movel에서 문제 생기면 이걸로 되돌리기
USE_MOVEL = True

# ---------------------------------------------------------------- 집기 / 무게 감지
LIFT_Z_MM = 30.0           # 잡은 뒤 들어 올리는 높이 (+Z, mm)
WEIGHT_THRESHOLD_N = 0.7   # 들기 전/후 Fz 차이가 이 값(N) 이상이면 '무게 감지됨' (실측 후 조정)
FORCE_SAMPLES = 5          # 힘 측정 평균 낼 횟수
FORCE_SAMPLE_INTERVAL = 0.1  # 측정 간격 (s)
SETTLE_SEC = 0.5           # 움직임이 끝나고 힘을 재기 전 기다리는 시간 (s)

# movel이 도착했는지 확인할 때 허용 오차 (mm). 못 가는 좌표(NOT REACHABLE)면 movel이
# 에러 없이 그냥 넘어가므로, 이동 뒤 현재 위치를 재서 확인한다.
REACH_TOL_MM = 3.0

# ---------------------------------------------------------------- 판재 빼기
BED_LENGTH_MM = 215.0      # 판재(베드) 길이 (참고용)
PULL_OUT_MM = 230.0        # 들어 올린 뒤 -X로 빼는 거리 (판재 길이 + 여유 15mm)

# ---------------------------------------------------------------- 작업대에 판재 넣기
INSERT_VELX, INSERT_ACCX = 30.0, 30.0   # 좌우로 흔들며 정렬할 때 속도 (느리게)
STRAIGHT_VELX, STRAIGHT_ACCX = 10.0, 10.0  # 정렬 뒤 깊숙이 일자로 밀어 넣을 때 속도 (더 느리게)
WIGGLE_ENABLE = False      # True: 처음 WIGGLE_DEPTH_MM 동안 좌우로 흔들며 들어감 / False: 흔들지 않고 바로 일자로
WIGGLE_Y_MM = 3.0          # 입구에서 좌우(Y)로 흔드는 최대 폭 (+-3mm)
WIGGLE_DEPTH_MM = 30.0     # 처음 이만큼 들어가는 동안 좌우로 흔들며 정렬
WIGGLE_STEP_MM = 10.0      # 흔들기 한 번마다 앞으로 가는 거리
WIGGLE_Y_STEP_MM = 0.5     # 옆으로 갈 때 이만큼씩 가며 매번 옆 힘(Fy) 확인
WIGGLE_CONTACT_N = 3.0     # 옆 힘 변화가 이 값 이상이면 옆에 닿음 -> 반대로 물러나기
WIGGLE_BACKOFF_MM = 5.0    # 옆에 닿으면 반대 방향으로 이만큼 (0.5cm) 물러남 (힘이 안 풀리면 한 번 더)
WIGGLE_BACKOFF_MAX_MM = 5.0  # 이만큼 물러나도 힘이 안 풀리면 멈춤 (잡은 채로)
WIGGLE_FORCE_SAMPLES = 2   # 흔들 때 한 번 재는 횟수 (적을수록 빠름)
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
DONE_REACT_N = 1.5         # 미는 방향 반력(기준 대비)이 이 값 이상이면 '힘 맞음' (PUSH_FORCE_N보다 작아야 함)
# (예전 CONTACT_LAG_MM '덜 감' 판정은 뺐음: 무른 순응 제어에서 가이드 마찰만으로도 걸려 끝 전에 멈췄음)
# 밀 때 순응 강성 (N/m, Nm/rad). 첫 값(X, 미는 방향)은 insert에서 PUSH_FORCE_N으로 다시 계산해서 덮어씀.
COMPLIANCE_STX = [500, 3000, 3000, 200, 200, 200]
# 진입 대기 위치에서 툴 Z축(판재 미는 방향)을 미는 방향(+X, 수평)에 맞춘 뒤 들어감 (판재 기울기 보정)
# 지금은 motion_test의 sd 명령에서만 사용 (sd -> 축정렬 -> insert는 정렬된 자세 유지). load2 액션은 안 함.
ALIGN_VECT = [1.0, 0.0, 0.0]   # 베이스 기준 미는 방향 (+X)
ALIGN_MAX_DEG = 15.0           # 지금 툴 Z축과 이 각도보다 많이 다르면 정렬 안 하고 멈춤 (안전)
PRE_INSERT_HOLD_SEC = 3.0      # sd 다음 첫 점(SD_PRE_INSERT)에서 멈추는 시간 (s)


# ---------------------------------------------------------------- 기본 동작 단위
def go_home() -> None:
    """홈(대기) 위치로 이동."""
    movej(posj(*poses.HOME_J), vel=VELJ, acc=ACCJ)


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


def go_ready(layer: int) -> None:
    """layer층 준비 위치(1단계: 홈 자리에서 그리퍼를 옆으로 눕힌 자세)로 이동.

    홈과 손목 자세(J5 90 -> -17)가 크게 달라 movel로 가면 J5=0 특이점을 지나므로 항상 movej.
    """
    movej(posj(*poses.START_POS_READY_J[layer]), vel=VELJ, acc=ACCJ)


def _movel_checked(pose_x: list) -> None:
    """movel 후 실제로 목표 위치(X, Y, Z)에 도착했는지 확인. 못 갔으면 예외 -> 다음 동작 안 함."""
    movel(posx(*pose_x), vel=VELX, acc=ACCX)
    cur = list(get_current_posx()[0])
    err = max(abs(cur[i] - pose_x[i]) for i in range(3))
    if err > REACH_TOL_MM:
        raise RuntimeError(
            f'목표 위치에 못 감 (NOT REACHABLE?) 목표={[round(v, 1) for v in pose_x[:3]]} '
            f'현재={[round(v, 1) for v in cur[:3]]}')


def go_entry_top(layer: int) -> None:
    """layer층 진입 전 X, Y 위치를 공통 진입 높이(ENTRY_LAYER층 진입 전 Z)로 직선 이동.

    여기서 Z로만 내리면(또는 올리면) layer층 진입 전이 된다.
    ENTRY_LAYER층 자신은 진입 전 위치와 같은 곳.
    """
    top = list(poses.START_POS_APPROACH_X[layer])
    top[2] = poses.START_POS_APPROACH_X[poses.ENTRY_LAYER][2]
    _movel_checked(top)


def _move_to(pose_j: list, pose_x: list) -> None:
    """USE_MOVEL에 따라 movel(posx) 또는 movej(posj)로 이동."""
    if USE_MOVEL:
        _movel_checked(pose_x)
    else:
        if pose_j is None:
            raise ValueError('관절 좌표(J)가 없어 movej로 갈 수 없음 (USE_MOVEL=True로 쓰거나 J 측정)')
        movej(posj(*pose_j), vel=VELJ, acc=ACCJ)


# ---------------------------------------------------------------- 이동 / 집기
class MotionStopped(Exception):
    """단계 진행 중 사용자가 멈춤 (motion_test의 board_step에서 사용)."""


def home_to_board(layer: int = 3, until: int | None = None, before_step=None) -> None:
    """홈(그리퍼 열기) -> 준비 -> 진입 높이 -> 진입 전(Z 수직 하강) -> 적재대 layer층 위치로 이동.

    until      : 이 단계까지만 가고 멈춤
                 (0=홈, 1=준비, 2=진입 높이, 3=진입 전, 4=적재대). None이면 끝까지.
    before_step: 각 단계 직전에 호출할 함수 f(단계번호, 이름). False를 돌려주면 거기서 멈춤.
    """
    for table, name in ((poses.START_POS_READY_J, 'START_POS_READY'),
                        (poses.START_POS_APPROACH_X, 'START_POS_APPROACH'),
                        (poses.START_POS_PICK_X, 'START_POS_PICK')):
        if layer not in table:
            raise ValueError(f'{name}에 {layer}층 좌표 없음 (가능: {list(table)})')

    steps = [
        ('홈 (그리퍼 열기)', lambda: (go_home(), grip_open())),  # 홈은 항상 movej
        (f'적재대 {layer}층 준비', lambda: go_ready(layer)),  # 준비도 항상 movej
        (f'진입 높이 (적재대 {poses.ENTRY_LAYER}층 진입 전 높이)', lambda: go_entry_top(layer)),
        (f'적재대 {layer}층 진입 전 (Z로 수직 하강)',
         lambda: _move_to(poses.START_POS_APPROACH_J.get(layer), poses.START_POS_APPROACH_X[layer])),
        (f'적재대 {layer}층',
         lambda: _move_to(poses.START_POS_PICK_J.get(layer), poses.START_POS_PICK_X[layer])),
    ]
    for i, (name, move) in enumerate(steps):
        if until is not None and i > until:
            return
        if before_step is not None and before_step(i, name) is False:
            raise MotionStopped(f'{i}단계({name}) 전에 멈춤')
        move()


def grip_and_check(pose_x: list, log=print) -> bool:
    """지금 위치(pose_x)에서 잡고 +Z로 들어 올린 뒤, 무게가 늘었는지 확인.

    1) 잡기 전 Fz 측정 (기준값)
    2) 그리퍼 닫기
    3) +Z LIFT_Z_MM 만큼 들어 올리기
    4) 다시 Fz 측정 -> |차이| >= WEIGHT_THRESHOLD_N 이면 True
    """
    wait(SETTLE_SEC)
    before = read_fz()
    grip_close()
    lifted = list(pose_x)
    lifted[2] += LIFT_Z_MM
    _movel_checked(lifted)
    wait(SETTLE_SEC)
    after = read_fz()
    diff = after - before
    picked = abs(diff) >= WEIGHT_THRESHOLD_N
    log(f'[무게 감지] 전 Fz={before:.2f}N  후 Fz={after:.2f}N  차이={diff:+.2f}N  '
        f'기준={WEIGHT_THRESHOLD_N}N  -> {picked}')
    return picked


def pull_out(dist: float = PULL_OUT_MM, log=print) -> None:
    """지금 위치에서 높이(Z), 옆(Y), 자세는 그대로 두고 -X로 dist(mm)만큼 일자로 빼기.

    판재를 잡고 들어 올린 상태(grip_and_check 뒤)에서 쓴다. 그리퍼는 그대로.
    못 가는 거리면(J3 한계) 그 자리에서 예외가 난다 (_movel_checked).
    가상 로봇 확인: 3층(Z 370)은 230mm 가능, 2층(Z 278)은 150mm까지, 1층(Z 185)은 100mm까지.
    """
    cur = list(get_current_posx()[0])
    target = list(cur)
    target[0] -= dist
    log(f'[빼기] X {cur[0]:.1f} -> {target[0]:.1f} (-{dist:.0f}mm), Y {cur[1]:.1f}, Z {cur[2]:.1f} 유지')
    _movel_checked(target)


def _check_sd_layer(layer: int) -> None:
    if layer not in poses.SD_POS_X:
        raise ValueError(f'SD_POS에 {layer}층 좌표 없음 (가능: {list(poses.SD_POS_X)})')


def go_sd(layer: int = 3, log=print) -> None:
    """판재를 빼낸(pull_out) 상태에서 작업대 layer층으로 이동. 그리퍼는 그대로.

    1) 작업대 3층(SD_TOP_LAYER) 위치로 movej (큰 회전이라 실측 관절값으로)
    2) layer가 3층이 아니면 movel로 그 층 좌표까지 내려감

    안전 확인: 판재가 아직 적재대 안에 있으면(지금 X가 잡는 곳 X - 판재 길이보다 앞) 움직이지 않는다.
    """
    _check_sd_layer(layer)
    cur = list(get_current_posx()[0])
    # 적재대 쪽(+Y, 적재대 Y - 100mm 보다 큼)이면서 X가 잡는 곳 X - 판재 길이보다 앞이면 아직 안에 있음.
    # 작업대 쪽(-Y)에 있을 때는 X와 상관없이 통과 (예: 작업대 3층에서 sd 1로 내려가기).
    limit_x = min(x[0] for x in poses.START_POS_PICK_X.values()) - BED_LENGTH_MM
    rack_y = min(x[1] for x in poses.START_POS_PICK_X.values()) - 100.0
    if cur[1] > rack_y and cur[0] > limit_x:
        raise RuntimeError(
            f'판재가 아직 적재대 안에 있을 수 있음 (지금 X={cur[0]:.1f} > {limit_x:.1f}, '
            f'Y={cur[1]:.1f} > {rack_y:.1f}). pullout 먼저 할 것')

    top = poses.SD_TOP_LAYER
    log(f'[작업대] 지금 {[round(v, 1) for v in cur[:3]]} -> 작업대 {top}층 {poses.SD_POS_X[top][:3]} (movej)')
    movej(posj(*poses.SD_POS_J[top]), vel=VELJ, acc=ACCJ)
    j = list(get_current_posj())
    err = max(abs(j[i] - poses.SD_POS_J[top][i]) for i in range(6))
    if err > 1.0:
        raise RuntimeError(
            f'작업대 {top}층에 못 감: 목표 J={poses.SD_POS_J[top]} 현재 J={[round(v, 1) for v in j]}')

    if layer != top:
        log(f'[작업대] {top}층 -> {layer}층 {poses.SD_POS_X[layer][:3]} (movel 하강)')
        _movel_checked(poses.SD_POS_X[layer])


def read_force_xyz(samples: int = FORCE_SAMPLES) -> list:
    """베이스 기준 툴 외력 [Fx, Fy, Fz](N) 평균."""
    total = [0.0, 0.0, 0.0]
    for _ in range(samples):
        f = get_tool_force(DR_BASE)
        for i in range(3):
            total[i] += float(f[i])
        wait(FORCE_SAMPLE_INTERVAL)
    return [v / samples for v in total]


def _along(a: list, b: list, d: float) -> list:
    """a -> b 직선 위에서 a로부터 d(mm) 떨어진 점 (자세도 같은 비율로 보간)."""
    length = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
    t = d / length
    return [a[i] + (b[i] - a[i]) * t for i in range(6)]


def _tool_z_dir(ori: list) -> list:
    """posx 자세(ZYZ 오일러, deg) -> 베이스 기준 툴 Z축 방향 단위벡터."""
    a, b = math.radians(ori[0]), math.radians(ori[1])
    return [math.cos(a) * math.sin(b), math.sin(a) * math.sin(b), math.cos(b)]


def align_push_axis(log=print) -> list:
    """지금 위치에서 툴 Z축(미는 방향)을 ALIGN_VECT(+X)에 맞춤 (align_axis). 정렬된 자세 [A,B,C] 반환.

    지금 툴 Z축과 ALIGN_VECT의 각도가 ALIGN_MAX_DEG보다 크면 (축을 잘못 골랐거나 자세가 이상)
    크게 돌아갈 수 있으므로 움직이지 않고 예외.
    """
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


def _insert_line(layer: int) -> tuple[list, list, list, float]:
    """넣는 직선 (입구, 끝, 방향 단위벡터, 길이mm). 입구 = SD_INSERT_FRONT, 끝 = SD_INSERT_DONE."""
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


def _wiggle_side(center: list, side: int, base: list, log, label: str) -> None:
    """center에서 side(+1 좌 / -1 우) 방향으로 WIGGLE_Y_STEP_MM씩 최대 WIGGLE_Y_MM까지 가며 Fy 확인.

    옆 힘 변화 >= WIGGLE_CONTACT_N 이면 거기서 멈추고, 반대 방향으로 WIGGLE_BACKOFF_MM씩
    힘이 풀릴 때까지 물러난다 (최대 WIGGLE_BACKOFF_MAX_MM, 그래도 안 풀리면 예외).
    앞(X) 힘 변화가 JAM_FORCE_N 넘으면 예외 (잡은 채로 멈춤).
    """
    name = '좌' if side > 0 else '우'

    def go(off: float) -> tuple[float, float]:
        q = list(center)
        q[1] += side * off
        movel(posx(*q), vel=INSERT_VELX, acc=INSERT_ACCX)
        f = read_force_xyz(WIGGLE_FORCE_SAMPLES)
        dfx, dfy = f[0] - base[0], f[1] - base[1]
        if abs(dfx) >= JAM_FORCE_N:
            raise RuntimeError(f'넣다가 앞이 걸림 ({label} {name} {off:.1f}mm: dFx={dfx:+.1f}N, '
                               f'기준 {JAM_FORCE_N}N) -> 멈춤, 그리퍼는 잡은 상태')
        return dfx, dfy

    off = 0.0
    while off < WIGGLE_Y_MM - 1e-9:
        off = min(off + WIGGLE_Y_STEP_MM, WIGGLE_Y_MM)
        dfx, dfy = go(off)
        if abs(dfy) >= WIGGLE_CONTACT_N:
            log(f'  [{label} {name}] {off:.1f}mm에서 옆에 닿음 dFy={dfy:+.1f}N -> 반대로 '
                f'{WIGGLE_BACKOFF_MM}mm씩 물러나기')
            backed = 0.0
            first_sign = 1.0 if dfy > 0 else -1.0
            while abs(dfy) >= WIGGLE_CONTACT_N:
                if backed >= WIGGLE_BACKOFF_MAX_MM - 1e-9:
                    where = ('반대쪽 옆에 닿음 (물러난 거리가 가이드 폭보다 큼)'
                             if dfy * first_sign < 0 else '옆 힘이 안 풀림')
                    raise RuntimeError(f'{label} {name}: {backed:.1f}mm 물러났는데 {where} '
                                       f'(옆 {side * off:+.1f}mm, dFy={dfy:+.1f}N) -> 멈춤, 그리퍼는 잡은 상태')
                backed += WIGGLE_BACKOFF_MM
                off -= WIGGLE_BACKOFF_MM
                dfx, dfy = go(off)
            log(f'  [{label} {name}] {backed:.1f}mm 물러나서 힘 풀림 (옆 {side * off:+.1f}mm, dFy={dfy:+.1f}N)')
            return
    log(f'  [{label} {name}] {WIGGLE_Y_MM:.1f}mm까지 안 닿음 (dFy={dfy:+.1f}N)')


def insert_sd(layer: int = 3, log=print, keep_ori: bool = False) -> bool:
    """작업대 layer층에 판재를 넣고, 끝 위치 + 반력이 맞으면 놓기. 자세는 측정값 그대로.

    0) SD_PRE_INSERT (sd 다음 첫 점)로 movel -> PRE_INSERT_HOLD_SEC(3초) 멈춤
    1) 입구(SD_INSERT_FRONT)로 movel
    2) WIGGLE_ENABLE이면 처음 WIGGLE_DEPTH_MM 동안 좌우(Y)로 흔들기 (지금은 False -> 안 함)
    3) 입구 -> 끝(SD_INSERT_DONE) 직선으로, 끝 PUSH_START_BEFORE_MM 앞까지 넣기
    4) 순응 제어 켜고(X 강성 = PUSH_FORCE_N / PUSH_OVERSHOOT_MM) 같은 직선 방향으로 PUSH_STEP_MM씩
       (끝 + PUSH_OVERSHOOT_MM까지) 밀며 매번 확인
       - 위치 도착 (직선 진행 >= 길이 - DONE_POS_TOL_MM) 그리고
         힘 맞음 (미는 방향 반력 >= DONE_REACT_N)
         -> 넣기 완료 -> 순응 해제(그 자리 고정) -> 그리퍼 열기 -> True
       - 끝까지 밀어도 완료 아님 -> False (잡은 채로)
    keep_ori는 예전 호환용 (지금은 측정 자세를 쓰므로 무시).
    위치 이동 중 힘이 JAM_FORCE_N 넘으면 예외 (잡은 채로 멈춤).
    """
    front, done, u, length = _insert_line(layer)
    pre = list(poses.SD_PRE_INSERT_X[layer])
    log(f'[넣기] 첫 점 {pre[:3]} -> 입구 {front[:3]} -> 끝 {done[:3]} '
        f'(직선 {length:.1f}mm, 방향 {[round(v, 3) for v in u]})')
    if keep_ori:
        log('[넣기] (sd 축정렬 자세 대신 측정한 자세를 씀)')

    _movel_checked(pre)
    log(f'[넣기] {PRE_INSERT_HOLD_SEC}초 멈춤')
    wait(PRE_INSERT_HOLD_SEC)
    log(f'[넣기] 입구 {front[:3]} 자세 {front[3:6]}')
    _movel_checked(front)
    wait(SETTLE_SEC)
    base = read_force_xyz()
    log(f'[넣기] 기준 힘 Fx={base[0]:.1f} Fy={base[1]:.1f} Fz={base[2]:.1f}N')

    # 2) 좌우로 흔들며 정렬 (WIGGLE_ENABLE일 때만)
    d = 0.0
    if not WIGGLE_ENABLE:
        log('[넣기] 좌우 흔들기 안 함 -> 바로 일자로 넣기')
    while WIGGLE_ENABLE and d < WIGGLE_DEPTH_MM:
        d = min(d + WIGGLE_STEP_MM, WIGGLE_DEPTH_MM)
        p = _point_on_line(front, done, d)
        _insert_move(p, base, log, f'정렬 {d:.0f}mm 가운데')
        for side in (+1, -1):
            _wiggle_side(p, side, base, log, f'정렬 {d:.0f}mm')
        _insert_move(p, base, log, f'정렬 {d:.0f}mm 가운데')

    # 3) 직선으로 끝 PUSH_START_BEFORE_MM 앞까지
    s0 = length - PUSH_START_BEFORE_MM
    _insert_move(_point_on_line(front, done, s0), base, log, '일자로 넣기',
                 vel=STRAIGHT_VELX, acc=STRAIGHT_ACCX)

    # 4) 순응 제어로 같은 직선 방향으로 밀면서 끝 위치 + 반력 확인
    wait(SETTLE_SEC)
    base = read_force_xyz()
    s_max = length + PUSH_OVERSHOOT_MM
    log(f'[넣기] 순응 제어로 밀기: 직선 {s0:.1f} -> 최대 {s_max:.1f}mm, {PUSH_STEP_MM:.0f}mm씩 '
        f'(완료: 진행 >= {length - DONE_POS_TOL_MM:.1f}mm 그리고 반력 >= {DONE_REACT_N}N)')
    # X 강성: 끝에 막힌 채 목표가 끝 + PUSH_OVERSHOOT_MM이면 PUSH_FORCE_N으로 누르게
    stx = list(COMPLIANCE_STX)
    stx[0] = PUSH_FORCE_N / (PUSH_OVERSHOOT_MM / 1000.0)
    log(f'[넣기] 순응 강성 X {stx[0]:.0f}N/m ({stx[0] / 1000:.2f}N/mm, 끝 +{PUSH_OVERSHOOT_MM:.0f}mm에서 약 {PUSH_FORCE_N}N)')
    finished = False
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
            reached = s_now >= length - DONE_POS_TOL_MM
            force_ok = react >= DONE_REACT_N
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
        # 순응 해제 = 지금 위치에서 위치 제어로 고정. 이걸 먼저 해야 그리퍼를 열었을 때
        # 눌려 있던 스프링 힘 때문에 손목이 앞으로 튀어 나가지 않는다.
        release_compliance_ctrl()
    if finished:
        grip_open()
        log('[넣기] 그리퍼 열기 (판재 놓음)')
    return finished


def retreat_sd(layer: int = 3, log=print) -> None:
    """(insert로 판재를 놓은 뒤) 그리퍼만 넣은 직선 그대로 거꾸로 빼서 입구 -> 첫 점으로. 그리퍼는 그대로."""
    front, done, _, _ = _insert_line(layer)
    pre = list(poses.SD_PRE_INSERT_X[layer])
    cur = list(get_current_posx()[0])
    log(f'[빼기] 지금 {[round(v, 1) for v in cur[:3]]} -> 입구 {front[:3]} -> 첫 점 {pre[:3]} (그리퍼 그대로)')
    for name, target in (('입구', front), ('첫 점', pre)):
        movel(posx(*target), vel=INSERT_VELX, acc=INSERT_ACCX)
        now = list(get_current_posx()[0])
        err = max(abs(now[i] - target[i]) for i in range(3))
        if err > REACH_TOL_MM:
            raise RuntimeError(f'{name}까지 못 뺌: 목표={[round(v, 1) for v in target[:3]]} '
                               f'현재={[round(v, 1) for v in now[:3]]}')
    log('[빼기] 첫 점 도착')


# ---------------------------------------------------------------- 액션 콜백에서 호출
def run_load1(goal: Load1.Goal, log=print) -> bool:
    """Load1: 홈 -> 적재대(start_pos_id층) -> 잡고 +Z 들어 올려 무게 확인 -> 그 자리에서 멈춤.

    반환값: 판재 무게가 감지됐으면 True, 아니면 False (액션 result.success로 전달됨)
    좌표 없는 층 번호가 오면 움직이기 전에 실패(예외) 처리된다.
    """
    layer = goal.start_pos_id
    log(f'[load1] 적재대 {layer}층')
    home_to_board(layer)
    return grip_and_check(poses.START_POS_PICK_X[layer], log=log)


def run_load(goal: Load.Goal, log=print) -> bool:
    """Load: 홈 -> 적재대(start_pos_id층) -> 잡고 +Z 들어 올려 무게 확인 -> 그 자리에서 멈춤.

    반환값: 판재 무게가 감지됐으면 True, 아니면 False (액션 result.success로 전달됨)
    좌표 없는 층 번호가 오면 움직이기 전에 실패(예외) 처리된다.
    """
    layer = goal.start_pos_id
    log(f'[load] 적재대 {layer}층')
    home_to_board(layer)
    return grip_and_check(poses.START_POS_PICK_X[layer], log=log)  # 들어 올린 상태로 끝


def run_load2(goal: Load2.Goal, log=print) -> bool:
    """Load2: (Load로 판재를 잡고 들어 올린 상태에서) 빼기 -> 작업대 sd_pos_id층으로 이동.

    1) pull_out: 높이 그대로 -X로 PULL_OUT_MM(230mm) 일자로 빼기
    2) go_sd   : 작업대 3층으로 movej -> sd_pos_id층이면 movel로 내려감
    좌표 없는 층 번호가 오면 움직이기 전에 실패(예외) 처리된다.
    """
    layer = goal.sd_pos_id
    _check_sd_layer(layer)
    log(f'[load2] 빼기 -> 작업대 {layer}층')
    pull_out(log=log)
    go_sd(layer, log=log)
    if layer not in poses.SD_INSERT_DONE_X:
        log(f'[load2] 작업대 {layer}층 넣기 좌표 없음 -> 작업대 앞에서 멈춤')
        return True
    return insert_sd(layer, log=log)  # 턱에 걸려 놓았으면 True, 아니면 False (잡은 채로)


def run_unload1(goal: Unload1.Goal, log=print) -> bool:
    """Unload1: 아직 동작 없음. 홈 위치로만 이동."""
    log(f'[unload1] 아직 동작 없음 -> 홈 이동 (sd_pos_id={goal.sd_pos_id})')
    go_home()
    return True


def run_unload(goal: Unload.Goal, log=print) -> bool:
    """Unload: 아직 동작 없음. 홈 위치로만 이동."""
    go_home()
    return True
