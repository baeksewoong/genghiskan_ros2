"""
로봇 구체 동작 (Load / Unload).

robot_action_server.py가 goal을 받으면 여기의 run_load() / run_unload()를 호출한다.
  - 함수가 True(또는 None)를 돌려주면 -> 작업 성공 (success=True)
  - 함수가 False를 돌려주면           -> 작업 실패 (success=False, 예: 무게 감지 안 됨)
  - 함수 안에서 예외가 나면           -> 작업 실패 (success=False, message에 예외 내용)

주의: 이 파일은 DSR_ROBOT2를 맨 위에서 import 하므로, robot_action_server.py의
main()이 DR_init 설정(로봇 ID, 모델, 노드)을 끝낸 뒤에 import 된다.
이 파일을 단독으로 import 하거나 실행하면 안 된다.
"""
from __future__ import annotations

from DR_common2 import posj, posx
from DSR_ROBOT2 import (
    DR_BASE,
    OFF,
    ON,
    get_tool_force,
    movej,
    movel,
    set_digital_output,
    wait,
)

from sfarm_interfaces.action import Load, Unload

from . import poses

# ---------------------------------------------------------------- 속도
VELJ, ACCJ = 30.0, 30.0      # 관절 이동 (movej)
VELX, ACCX = 100.0, 100.0    # 직선 이동 (movel)

# True: 아직 만드는 중인 단계별 동작만 한다 (load: 홈 <-> 적재대 3층, unload: 홈 이동).
# False: poses.py 좌표표로 전체 동작(집기/놓기)을 한다. 좌표를 다 채우면 False로 바꾼다.
TEST_MODE = True

# 홈 -> 적재대 경로 이동 방식
#   True : movel (posx, 직선 이동)
#   False: movej (posj, 관절 이동) - movel에서 문제 생기면 이걸로 되돌리기
USE_MOVEL = True

# ---------------------------------------------------------------- 집기 / 무게 감지
LIFT_Z_MM = 30.0           # 잡은 뒤 들어 올리는 높이 (+Z, mm)
WEIGHT_THRESHOLD_N = 1.5   # 들기 전/후 Fz 차이가 이 값(N) 이상이면 '무게 감지됨' (실측 후 조정)
FORCE_SAMPLES = 5          # 힘 측정 평균 낼 횟수
FORCE_SAMPLE_INTERVAL = 0.1  # 측정 간격 (s)
SETTLE_SEC = 0.5           # 움직임이 끝나고 힘을 재기 전 기다리는 시간 (s)


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
    movel(posx(*lifted), vel=VELX, acc=ACCX)
    wait(SETTLE_SEC)
    after = read_fz()
    diff = after - before
    picked = abs(diff) >= WEIGHT_THRESHOLD_N
    log(f'[무게 감지] 전 Fz={before:.2f}N  후 Fz={after:.2f}N  차이={diff:+.2f}N  '
        f'기준={WEIGHT_THRESHOLD_N}N  -> {picked}')
    return picked


def pick(approach: list, target: list) -> None:
    """approach 위에서 내려가서 target을 잡고 다시 올라온다."""
    movel(posx(*approach), vel=VELX, acc=ACCX)
    grip_open()
    movel(posx(*target), vel=VELX, acc=ACCX)
    grip_close()
    movel(posx(*approach), vel=VELX, acc=ACCX)


def place(approach: list, target: list) -> None:
    """approach 위에서 내려가서 target에 놓고 다시 올라온다."""
    movel(posx(*approach), vel=VELX, acc=ACCX)
    movel(posx(*target), vel=VELX, acc=ACCX)
    grip_open()
    movel(posx(*approach), vel=VELX, acc=ACCX)


def _move_to(pose_j: list, pose_x: list) -> None:
    """USE_MOVEL에 따라 movel(posx) 또는 movej(posj)로 이동."""
    if USE_MOVEL:
        movel(posx(*pose_x), vel=VELX, acc=ACCX)
    else:
        movej(posj(*pose_j), vel=VELJ, acc=ACCJ)


class MotionStopped(Exception):
    """단계 진행 중 사용자가 멈춤 (motion_test의 board_step에서 사용)."""


def home_to_board(layer: int = 3, until: int | None = None, before_step=None) -> None:
    """홈 -> move1 -> move2 -> 진입 전 -> 적재대 layer층 위치로 이동.

    until      : 이 단계까지만 가고 멈춤
                 (0=홈, 1=move1, 2=move2, 3=진입 전, 4=적재대). None이면 끝까지.
    before_step: 각 단계 직전에 호출할 함수 f(단계번호, 이름). False를 돌려주면 거기서 멈춤.
    """
    for table, name in ((poses.BOARD_APPROACH_J, 'BOARD_APPROACH'),
                        (poses.BOARD_LAYER_J, 'BOARD_LAYER')):
        if layer not in table:
            raise ValueError(f'{name}에 {layer}층 좌표 없음 (가능: {list(table)})')

    steps = [
        ('홈 (그리퍼 열기)', lambda: (go_home(), grip_open())),  # 홈은 항상 movej
        ('move1', lambda: _move_to(poses.MOVE1_J, poses.MOVE1_X)),
        ('move2', lambda: _move_to(poses.MOVE2_J, poses.MOVE2_X)),
        (f'적재대 {layer}층 진입 전',
         lambda: _move_to(poses.BOARD_APPROACH_J[layer], poses.BOARD_APPROACH_X[layer])),
        (f'적재대 {layer}층',
         lambda: _move_to(poses.BOARD_LAYER_J[layer], poses.BOARD_LAYER_X[layer])),
    ]
    for i, (name, move) in enumerate(steps):
        if until is not None and i > until:
            return
        if before_step is not None and before_step(i, name) is False:
            raise MotionStopped(f'{i}단계({name}) 전에 멈춤')
        move()


def board_to_home(layer: int = 3, lifted: bool = False) -> None:
    """적재대 layer층 -> 진입 전 -> move2 -> move1 -> 홈 (갈 때 경로를 거꾸로).

    lifted=True : 판재를 LIFT_Z_MM 들어 올린 상태. 진입 전 지점도 같은 높이(+Z)로 빠져서
                  판재가 선반에 긁히지 않게 한다.
    """
    if layer not in poses.BOARD_APPROACH_J:
        raise ValueError(f'BOARD_APPROACH에 {layer}층 좌표 없음 (가능: {list(poses.BOARD_APPROACH_J)})')
    if lifted:
        back = list(poses.BOARD_APPROACH_X[layer])
        back[2] += LIFT_Z_MM
        movel(posx(*back), vel=VELX, acc=ACCX)
    else:
        _move_to(poses.BOARD_APPROACH_J[layer], poses.BOARD_APPROACH_X[layer])
    _move_to(poses.MOVE2_J, poses.MOVE2_X)
    _move_to(poses.MOVE1_J, poses.MOVE1_X)
    go_home()  # 홈은 항상 movej


def put_back_and_leave(layer: int = 3) -> None:
    """(수동용) 들어 올린 상태에서: 판재 제자리에 내려놓고(-Z) 그리퍼 열고 -> 뒤로 빠져서 홈."""
    movel(posx(*poses.BOARD_LAYER_X[layer]), vel=VELX, acc=ACCX)
    grip_open()
    board_to_home(layer, lifted=False)


def pick_from_board(layer: int = 3, log=print) -> bool:
    """홈 -> 적재대 layer층 -> 잡고 들어 올려 무게 확인 -> 홈 복귀. 무게 감지 결과를 돌려준다.

    무게가 감지 안 되면(못 잡았으면) 그리퍼를 열고 복귀한다.
    """
    home_to_board(layer)
    picked = grip_and_check(poses.BOARD_LAYER_X[layer], log=log)
    if not picked:
        grip_open()
    board_to_home(layer, lifted=True)
    return picked


# ---------------------------------------------------------------- 작업 시퀀스
def run_load(goal: Load.Goal, log=print) -> bool:
    """Load: 판재 적재대(start_pos_id)에서 집어서 3D 프린터(pos_3d_id)에 넣기.

    반환값: 판재 무게가 감지됐으면 True, 아니면 False (액션 result.success로 전달됨)
    """
    if TEST_MODE:
        # 지금 단계: 홈 -> 적재대(3층) -> 잡고 +Z 들어 올려 무게 확인 -> 그 자리에서 멈춤
        layer = 3
        home_to_board(layer)
        return grip_and_check(poses.BOARD_LAYER_X[layer], log=log)  # 들어 올린 상태로 끝

    # 움직이기 전에 좌표부터 전부 꺼낸다 (비어 있으면 여기서 실패하고 로봇은 안 움직임)
    s, p = goal.start_pos_id, goal.pos_3d_id
    board_approach = poses.get_pose(poses.BOARD_STOCK, s, 'approach', 'BOARD_STOCK')
    board_pick = poses.get_pose(poses.BOARD_STOCK, s, 'pick', 'BOARD_STOCK')
    printer_approach = poses.get_pose(poses.PRINTER, p, 'approach', 'PRINTER')
    printer_place = poses.get_pose(poses.PRINTER, p, 'place', 'PRINTER')

    go_home()
    pick(board_approach, board_pick)
    place(printer_approach, printer_place)
    go_home()
    return True


def run_unload(goal: Unload.Goal, log=print) -> bool:
    """Unload: 3D 프린터(pos_3d_id)에서 빼서 수령대(receive_pos_id)에 놓기."""
    if TEST_MODE:
        # 아직 unload 동작 없음: 홈 위치로만 이동
        go_home()
        return True

    # 움직이기 전에 좌표부터 전부 꺼낸다 (비어 있으면 여기서 실패하고 로봇은 안 움직임)
    p, r = goal.pos_3d_id, goal.receive_pos_id
    printer_approach = poses.get_pose(poses.PRINTER, p, 'approach', 'PRINTER')
    printer_pick = poses.get_pose(poses.PRINTER, p, 'place', 'PRINTER')
    receive_approach = poses.get_pose(poses.RECEIVE, r, 'approach', 'RECEIVE')
    receive_place = poses.get_pose(poses.RECEIVE, r, 'place', 'RECEIVE')

    go_home()
    pick(printer_approach, printer_pick)
    place(receive_approach, receive_place)
    go_home()
    return True
