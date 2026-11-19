"""
모션 단독 테스트 (액션 서버 / 브리지 없이 motions.py 함수만 바로 실행).

액션 서버가 쓰는 motions.py / poses.py를 그대로 불러와서 실행하므로,
여기서 확인한 동작이 액션 서버에서도 똑같이 나온다.
메뉴 모드에서도 명령마다 motions.py / poses.py를 다시 읽으므로,
파일을 고치고 저장한 뒤 같은 메뉴에서 바로 다시 실행하면 된다 (재시작 불필요).

사용법
  ros2 run sfarm_robot motion_test              # 메뉴에서 골라서 실행 (반복)
  ros2 run sfarm_robot motion_test board 3      # 바로 실행: 홈 -> 적재대 3층
  ros2 run sfarm_robot motion_test board 2 2    # 진입 높이(2단계)까지만 가고 멈춤 (3=진입 전, 4=적재대)
  ros2 run sfarm_robot motion_test board_step 3 # 한 단계씩 Enter로 진행
  ros2 run sfarm_robot motion_test load 1       # 바로 실행: run_load(start_pos_id=1) (액션과 같은 동작)

주의: 액션 서버(robot_action_server)와 동시에 로봇을 움직이지 말 것.
"""
import importlib
import sys

import DR_init
import rclpy

ROBOT_ID = 'dsr01'
ROBOT_MODEL = 'm0609'

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


# ---------------------------------------------------------------- 테스트용 동작
# 액션 콜백에서는 안 쓰고 이 메뉴에서만 쓰는 동작들 (motions.py의 기본 동작을 조합)
def board_to_home(motions, layer: int = 3, lifted: bool = False) -> None:
    """적재대 layer층 -> 진입 전 -> (Z로 수직 상승) 진입 높이 -> 준비 -> 홈 (갈 때 경로를 거꾸로).

    lifted=True : 판재를 LIFT_Z_MM 들어 올린 상태. 진입 전 지점도 같은 높이(+Z)로 빠져서
                  판재가 선반에 긁히지 않게 한다.
    """
    p = motions.poses
    if layer not in p.START_POS_APPROACH_X or layer not in p.START_POS_READY_J:
        raise ValueError(f'{layer}층 좌표 없음 (가능: {list(p.START_POS_APPROACH_X)})')
    if lifted:
        back = list(p.START_POS_APPROACH_X[layer])
        back[2] += motions.LIFT_Z_MM
        motions.movel(motions.posx(*back), vel=motions.VELX, acc=motions.ACCX)
    else:
        motions._move_to(p.START_POS_APPROACH_J.get(layer), p.START_POS_APPROACH_X[layer])
    motions.go_entry_top(layer)
    motions.go_ready(layer)
    motions.go_home()


def _current_x():
    from DSR_ROBOT2 import get_current_posx
    return list(get_current_posx()[0])


def move_z(motions, dz: float) -> None:
    """지금 위치에서 Z만 dz(mm) 만큼 직선 이동 (+ 올리기 / - 내리기). 그리퍼는 그대로."""
    cur = _current_x()
    target = list(cur)
    target[2] += dz
    print(f'  Z {cur[2]:.1f} -> {target[2]:.1f} mm ({dz:+.1f})')
    # 느리게 이동 + 실제로 갔는지 확인 (못 가는 높이면 에러로 알려 줌)
    motions.movel(motions.posx(*target), vel=motions.INSERT_VELX, acc=motions.INSERT_ACCX)
    now = _current_x()
    if abs(now[2] - target[2]) > motions.REACH_TOL_MM:
        raise RuntimeError(f'Z {target[2]:.1f}까지 못 감 (지금 Z {now[2]:.1f})')
    print(f'  도착: X={now[0]:.1f} Y={now[1]:.1f} Z={now[2]:.1f}')


def move_xy_to(motions, table_x: dict, layer: int, label: str) -> None:
    """지금 높이(Z)와 자세는 유지하고 X, Y만 table_x[layer] 위치로 직선 이동. 그리퍼는 그대로."""
    if layer not in table_x:
        raise ValueError(f'{label}에 {layer}층 좌표 없음 (가능: {list(table_x)})')
    cur = _current_x()
    target = list(table_x[layer])
    target[2] = cur[2]  # 높이는 지금 그대로
    print(f'  X {cur[0]:.1f} -> {target[0]:.1f}, Y {cur[1]:.1f} -> {target[1]:.1f}  (Z {cur[2]:.1f} 유지)')
    motions.movel(motions.posx(*target), vel=motions.VELX, acc=motions.ACCX)


def back_to_home(motions, layer: int = 3) -> None:
    """지금 위치에서 그리퍼 열기 -> 진입 전 지점으로 뒤로 빠짐 -> 진입 높이 -> 준비 -> 홈.

    홈으로 바로 가면 적재대에 부딪히므로 반드시 진입 전 지점을 거쳐서 나온다.
    뒤로 빠질 때 높이는 지금 높이를 그대로 유지한다
    (잡는 곳 높이면 진입 전 높이로, +30mm 들어 올린 상태면 진입 전 +30mm로).
    """
    from DSR_ROBOT2 import get_current_posx

    p = motions.poses
    if layer not in p.START_POS_APPROACH_X:
        raise ValueError(f'START_POS_APPROACH에 {layer}층 좌표 없음 (가능: {list(p.START_POS_APPROACH_X)})')
    cur_z = float(get_current_posx()[0][2])
    dz = cur_z - p.START_POS_PICK_X[layer][2]  # 잡는 곳 대비 지금 높이 차이
    print(f'  현재 Z={cur_z:.1f}mm (잡는 곳 대비 {dz:+.1f}mm) -> 진입 전도 같은 높이로 빠짐')

    motions.grip_open()
    back = list(p.START_POS_APPROACH_X[layer])
    back[2] += dz
    motions.movel(motions.posx(*back), vel=motions.VELX, acc=motions.ACCX)
    motions.go_entry_top(layer)
    motions.go_ready(layer)
    motions.go_home()


def put_back_and_leave(motions, layer: int = 3) -> None:
    """들어 올린 상태에서: 판재 제자리에 내려놓고(-Z) 그리퍼 열고 -> 뒤로 빠져서 홈."""
    motions.movel(motions.posx(*motions.poses.START_POS_PICK_X[layer]),
                  vel=motions.VELX, acc=motions.ACCX)
    motions.grip_open()
    board_to_home(motions, layer, lifted=False)


def pick_from_board(motions, layer: int = 3) -> bool:
    """홈 -> 적재대 -> 잡고 들어 올려 무게 확인 -> 홈 복귀 (못 잡았으면 그리퍼 열고 복귀)."""
    motions.home_to_board(layer)
    picked = motions.grip_and_check(motions.poses.START_POS_PICK_X[layer])
    if not picked:
        motions.grip_open()
    board_to_home(motions, layer, lifted=True)
    return picked


def build_commands(motions):
    """메뉴 이름 -> (설명, 실행 함수(인자 리스트)) 표."""
    from sfarm_interfaces.action import Load, Load1, Load2, Unload, Unload1

    from sfarm_robot import force_test  # 힘 측정 테스트 (DR_init 설정 후라 여기서 import)

    def pushtest(args):
        axis = args[0].lower() if len(args) > 0 else 'x'
        mm = float(args[1]) if len(args) > 1 else 20.0
        step = float(args[2]) if len(args) > 2 else 2.0
        force_test.pushtest(axis, mm, step)

    def sd(args):
        # 작업대로 이동한 뒤 툴 Z축을 미는 방향(+X)에 맞춤. 다음 insert는 이 자세 그대로 넣는다.
        # sd 3 force : 판재가 아직 적재대 안에 있어도 이동 (시험용)
        force = len(args) > 1 and args[1].lower() == 'force'
        motions.go_sd(int(args[0]) if args else 3, force=force)
        motions.align_push_axis()

    def j1(args):
        # J1(몸통)만 [도]만큼 돌리기 (- = 프린터 쪽). 나머지 관절 그대로 -> 몸통과 거리 그대로 (손목 한계 안 걸림)
        from DSR_ROBOT2 import get_current_posj
        deg = float(args[0]) if args else -5.0
        cur = list(get_current_posj())
        target = list(cur)
        target[0] += deg
        print(f'  J1 {cur[0]:.1f} -> {target[0]:.1f} deg ({deg:+.1f})')
        motions.movej(motions.posj(*target), vel=10.0, acc=10.0)
        now = list(get_current_posj())
        if abs(now[0] - target[0]) > 1.0:
            raise RuntimeError(f'J1 {target[0]:.1f}까지 못 감 (지금 {now[0]:.1f})')
        x = list(motions.get_current_posx()[0])
        print(f'  도착: X={x[0]:.1f} Y={x[1]:.1f} Z={x[2]:.1f}')

    def side(args):
        # 지금 높이/자세 그대로 Y로만 [mm] 직선 이동 (- = 프린터 쪽). 몸통과 가까워지면 못 갈 수 있음
        dy = float(args[0]) if args else -10.0
        cur = list(motions.get_current_posx()[0])
        target = list(cur)
        target[1] += dy
        print(f'  Y {cur[1]:.1f} -> {target[1]:.1f} mm ({dy:+.1f})')
        motions.movel(motions.posx(*target), vel=motions.INSERT_VELX, acc=motions.INSERT_ACCX)
        now = list(motions.get_current_posx()[0])
        if abs(now[1] - target[1]) > motions.REACH_TOL_MM:
            raise RuntimeError(f'Y {target[1]:.1f}까지 못 감 (지금 Y {now[1]:.1f})')
        print(f'  도착: X={now[0]:.1f} Y={now[1]:.1f} Z={now[2]:.1f}')

    def ry(args):
        # 그리퍼 끝 위치는 그대로, 베이스 Y축으로 [도]만큼 기울이기 (기본 +2, + = 판재 앞쪽 숙임)
        deg = float(args[0]) if args else 2.0
        if abs(deg) > RY_MAX_DEG:
            raise ValueError(f'한 번에 {RY_MAX_DEG}도까지만 (입력 {deg})')
        motions.tilt_ry(deg)
        now = list(motions.get_current_posx()[0])
        print(f'  도착: X={now[0]:.1f} Y={now[1]:.1f} Z={now[2]:.1f}  자세={[round(v, 2) for v in now[3:6]]}')

    def rot(axis):
        # 그리퍼 끝 위치는 그대로, 베이스 axis축으로 [도]만큼 돌리기 (기본 +2)
        def run(args):
            deg = float(args[0]) if args else 2.0
            if abs(deg) > RY_MAX_DEG:
                raise ValueError(f'한 번에 {RY_MAX_DEG}도까지만 (입력 {deg})')
            motions.tilt_base(axis, deg)
            now = list(motions.get_current_posx()[0])
            print(f'  도착: X={now[0]:.1f} Y={now[1]:.1f} Z={now[2]:.1f}  자세={[round(v, 2) for v in now[3:6]]}')
        return run

    def rackout(args):
        # load2 첫 부분만: 적재대에서 빼기. 그 층으로 가지는 않고 지금 위치에서 그 층 순서를 실행.
        # 층 번호를 주면 지금 높이로 판단한 층과 같은지 확인 (다르면 안 움직임)
        now = motions.rack_layer_now()
        if args:
            layer = int(args[0])
            if now != layer:
                raise RuntimeError(f'지금 위치는 {now}층(잡고 든 높이)이 아님 -> {layer}층 빼기 안 함. '
                                   f'load1 {layer} 먼저 할 것')
        else:
            layer = now
        print(f'  지금 위치: 적재대 {now}층')
        motions.exit_rack(layer)

    def load1(args):
        s = int(args[0]) if len(args) > 0 else 3
        return motions.run_load1(Load1.Goal(work_id=0, start_pos_id=s))

    def load2(args):
        s = int(args[0]) if args else 3
        return motions.run_load2(Load2.Goal(work_id=0, sd_pos_id=s))

    def load(args):
        s = int(args[0]) if len(args) > 0 else 3
        p = int(args[1]) if len(args) > 1 else 1
        return motions.run_load(Load.Goal(work_id=0, start_pos_id=s, pos_3d_id=p))

    def unload1(args):
        s = int(args[0]) if args else 3
        return motions.run_unload1(Unload1.Goal(work_id=0, sd_pos_id=s))

    def unload(args):
        p = int(args[0]) if len(args) > 0 else 1
        r = int(args[1]) if len(args) > 1 else 1
        return motions.run_unload(Unload.Goal(work_id=0, pos_3d_id=p, receive_pos_id=r))

    def check(args):
        # 지금 위치에서 잡고 +Z LIFT_Z_MM 들어 올려 무게 확인 (층 상관없음, 층 번호 안 받음)
        # (예전: 층 번호 기본 3 -> 2층에서 치면 3층 높이까지 올라갔음)
        cur = list(motions.get_current_posx()[0])
        print(f'[check] 지금 위치 {[round(v, 1) for v in cur[:3]]} 에서 잡고 +{motions.LIFT_Z_MM}mm')
        return motions.grip_and_check(cur)

    def leave(args):
        put_back_and_leave(motions, int(args[0]) if args else 3)

    def force(args):
        fz = motions.read_fz()
        print(f'  현재 Fz = {fz:.2f} N')

    def board(args):
        layer = int(args[0]) if len(args) > 0 else 3
        until = int(args[1]) if len(args) > 1 else None
        motions.home_to_board(layer, until=until)

    def board_step(args):
        layer = int(args[0]) if len(args) > 0 else 3

        def ask(i, name):
            ans = input(f'  [{i}단계] {name}(으)로 이동할까요? (Enter=진행, q=멈춤) ')
            return ans.strip().lower() != 'q'

        motions.home_to_board(layer, before_step=ask)

    return {
        'home': ('홈으로 바로 이동 (적재대 안에서는 쓰지 말 것 -> back)', lambda a: motions.go_home()),
        'board': ('홈 -> 적재대 [층=3] [멈출 단계: 0홈 1준비 2진입높이 3진입전 4적재대]', board),
        'board_step': ('홈 -> 적재대 [층=3] 한 단계씩 (Enter=진행, q=멈춤)', board_step),
        'j1': ('[시험] J1(몸통)만 [도]만큼 돌리기 (기본 -5, - = 프린터 쪽, 느리게) (그리퍼 그대로)', j1),
        'side': ('[시험] 높이 그대로 Y로 [mm] 직선 이동 (기본 -10, - = 프린터 쪽) (그리퍼 그대로)', side),
        'up': ('지금 위치에서 +Z로 [mm]만큼 올리기 (기본 30, 예: up 10) (그리퍼 그대로)',
               lambda a: move_z(motions, float(a[0]) if a else motions.LIFT_Z_MM)),
        'down': ('지금 위치에서 -Z로 [mm]만큼 내리기 (기본 30, 예: down 10) (그리퍼 그대로)',
                 lambda a: move_z(motions, -(float(a[0]) if a else motions.LIFT_Z_MM))),
        'out': ('지금 높이 그대로 진입 전 위치로 뒤로 빼기 [층=3] (그리퍼 그대로)',
                lambda a: move_xy_to(motions, motions.poses.START_POS_APPROACH_X,
                                     int(a[0]) if a else 3, 'START_POS_APPROACH')),
        'in': ('지금 높이 그대로 잡는 곳으로 앞으로 넣기 [층=3] (그리퍼 그대로)',
               lambda a: move_xy_to(motions, motions.poses.START_POS_PICK_X,
                                    int(a[0]) if a else 3, 'START_POS_PICK')),
        'pullout': ('(잡고 들어 올린 상태에서) 높이 그대로 -X로 일자로 빼기 [mm=230] (그리퍼 그대로)',
                    lambda a: motions.pull_out(float(a[0]) if a else motions.PULL_OUT_MM)),
        'rise': ('(pullout 후) 3층 높이까지 Z로만 수직으로 올라가기 (그리퍼 그대로)',
                 lambda a: motions.rise_to_top()),
        'sd': ('(pullout 후) 판재 든 채로 작업대 [층=3]으로 이동 -> 미는 방향 축정렬. [층] force = 적재대 안전 확인 건너뜀(시험용)',
               sd),
        'sda': ('[시험] (pullout 후) 언로드 정렬 자세(언로드3 Y/자세 + sd 3 높이)로 movej [층=3] [force=안전 확인 건너뜀]',
                lambda a: motions.go_sd_align(int(a[0]) if a and a[0].isdigit() else 3,
                                              force='force' in [s.lower() for s in a])),
        'sdain': ('[시험] (sda 후) 높이/자세 그대로 +X로 똑바로 넣기 [X=560(언로드3 X)] (그리퍼 그대로, 순응 없음)',
                  lambda a: motions.sd_align_in(3, float(a[0]) if a else None)),
        'ry': ('그리퍼 끝 위치 그대로 베이스 Y축으로 [도=2] 기울이기 (+ = 판재 앞쪽 숙임, - = 들림, 최대 20도)', ry),
        'fwd': ('미는 축(그리퍼가 보는 방향, 기울어져 있으면 그 방향)으로 [mm=10] 직선 이동 (+ = 앞, - = 뒤, 자세 그대로)',
                lambda a: motions.move_tool_z(float(a[0]) if a else 10.0)),
        'bwd': ('미는 축 반대(그리퍼가 보는 방향의 뒤)로 [mm=10] 직선 이동 (fwd의 반대, 자세 그대로)',
                lambda a: motions.move_tool_z(-abs(float(a[0])) if a else -10.0)),
        'rx': ('그리퍼 끝 위치 그대로 베이스 X축으로 [도=2] 돌리기 (그리퍼가 +X를 볼 때 판재 좌우로 눕히기, 최대 20도)', rot('x')),
        'rz': ('그리퍼 끝 위치 그대로 베이스 Z축으로 [도=2] 돌리기 (그리퍼가 +X를 볼 때 + = 왼쪽(+Y)으로 돌림, 최대 20도)', rot('z')),
        'rackout': ('(load1 N 후) 지금 위치에서 적재대 빼기만 (그 층으로 이동 안 함). [층]을 주면 지금 위치와 같은 층인지 확인. 다음은 sd 3',
                    rackout),
        'retreat': ('(insert로 놓은 뒤) 그리퍼만 넣은 길 그대로 거꾸로 빼서 진입 대기 위치로 [층=3] (그리퍼 그대로)',
                    lambda a: motions.retreat_sd(int(a[0]) if a else 3)),
        'insert': ('(sd 후) 작업대 [층=3]에 넣기 (sd에서 정렬한 자세 유지): 좌우 흔들며 진입 -> 순응 제어로 밀어 완료 위치+힘 맞으면 놓기  => True/False',
                   lambda a: motions.insert_sd(int(a[0]) if a else 3, keep_ori=True)),
        'load2': ('run_load2 [sd_pos_id(층)=3] (액션과 같은 동작: 빼기 -> 작업대 층)  => True/False',
                  load2),
        'back': ('(적재대 안에서) 그리퍼 열기 -> 진입 전으로 빠짐 -> 진입 높이 -> 준비 -> 홈 [층=3]',
                 lambda a: back_to_home(motions, int(a[0]) if a else 3)),
        'leave': ('(load/check 후 적재대에 멈춘 상태) 판재 내려놓고 그리퍼 열고 -> 홈 [층=3]', leave),
        'board_home': ('적재대 -> 홈 [층=3]', lambda a: board_to_home(motions, int(a[0]) if a else 3)),
        'pick': ('홈 -> 적재대 -> 잡고 +Z 들기 -> 무게 확인 -> 홈 [층=3]  => True/False',
                 lambda a: pick_from_board(motions, int(a[0]) if a else 3)),
        'pos': ('지금 좌표 출력 (안 움직임): posx [X, Y, Z, A, B, C] / posj [J1~J6]',
                lambda a: print('posx = [{}]\nposj = [{}]'.format(
                    *[', '.join(f'{v:.2f}' for v in vals) for vals in reversed(motions.get_current_poses())]))),
        'check': ('지금 위치에서 잡고 +Z 30mm 들기 -> 무게 확인 (층 상관없음)  => True/False', check),
        'force': ('현재 Fz(N) 측정', force),
        'grip': ('그리퍼 닫기', lambda a: motions.grip_close()),
        'release': ('그리퍼 열기', lambda a: motions.grip_open()),
        'load1': ('run_load1 [start_pos_id(층)=3]  => True/False', load1),
        'load': ('run_load [start_pos_id(층)=3] (액션과 같은 동작: 잡고 들기, 멈춤)  => True/False', load),
        'unload1': ('run_unload1 [sd_pos_id(층)=3] (액션과 같은 동작: 프린터 층 진입 -> 잡기+당기기 확인)  => True/False', unload1),
        'unload': ('run_unload (아직 동작 없음: 홈 이동)', unload),
        'fmon': ('[힘 테스트] 그 자리에서 힘 변화만 계속 출력 [초=10] (안 움직임)',
                 lambda a: force_test.fmon(float(a[0]) if a else 10.0)),
        'pushtest': ('[힘 테스트] 순응 제어로 [축=x] 방향 [mm=20]을 [step=2]씩 밀며 힘 출력 (그리퍼 그대로)',
                     pushtest),
    }


RY_MAX_DEG = 20.0   # ry 한 번에 돌릴 수 있는 최대 각도 (안전)


def run_one(commands, name, args, logger) -> None:
    """명령 하나 실행. 실패해도 프로그램은 계속 돈다."""
    if name not in commands:
        logger.error(f'모르는 명령: {name}  (가능: {", ".join(commands)})')
        return
    logger.info(f'▶ {name} {" ".join(args)}')
    try:
        ret = commands[name][1](args)
        if isinstance(ret, bool):
            logger.info(f'✔ {name} 완료  ==> 결과: {ret}')
        else:
            logger.info(f'✔ {name} 완료')
    except Exception as exc:  # noqa: BLE001
        logger.error(f'✘ {name} 실패: {exc}')


def print_menu(commands) -> None:
    print('\n----- 모션 테스트 -----')
    for i, (name, (desc, _)) in enumerate(commands.items(), 1):
        print(f'  {i}. {name:<11} {desc}')
    print('  q. 종료')
    print('입력 예: board 1  /  up  /  up 10  /  out 1  /  in 1  /  down  /  back 1  /  leave 1')


def main(args=None) -> None:
    """Entry point for motion_test."""
    rclpy.init(args=args)
    node = rclpy.create_node('sfarm_motion_test', namespace=ROBOT_ID)
    DR_init.__dsr__node = node
    logger = node.get_logger()

    try:
        # DR_init 설정이 끝난 뒤에 import 해야 한다 (motions.py가 DSR_ROBOT2를 import)
        from sfarm_robot import motions
    except ImportError as e:
        logger.error(f'Error importing DSR_ROBOT2 / motions: {e}')
        node.destroy_node()
        rclpy.shutdown()
        return

    commands = build_commands(motions)
    names = list(commands)
    cli = rclpy.utilities.remove_ros_args(sys.argv)[1:]

    try:
        if cli:
            # 바로 실행 모드: ros2 run sfarm_robot motion_test board 3
            run_one(commands, cli[0], cli[1:], logger)
        else:
            # 메뉴 모드
            while rclpy.ok():
                print_menu(commands)
                line = input('> ').strip().split()
                if not line:
                    continue
                if line[0].lower() in ('q', 'quit', 'exit'):
                    break
                name = line[0]
                if name.isdigit() and 1 <= int(name) <= len(names):
                    name = names[int(name) - 1]
                # 고친 코드 반영: poses -> motions 순서로 다시 읽기
                try:
                    importlib.reload(motions.poses)
                    importlib.reload(motions)
                    import sfarm_robot.force_test as _ft
                    importlib.reload(_ft)
                except Exception as exc:  # noqa: BLE001
                    logger.error(f'코드 다시 읽기 실패 (문법 오류?): {exc}')
                    continue
                commands = build_commands(motions)
                run_one(commands, name, line[1:], logger)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
