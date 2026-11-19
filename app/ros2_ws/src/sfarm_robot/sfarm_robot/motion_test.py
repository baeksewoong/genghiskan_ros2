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


WTEST_SAMPLES = 25        # wtest: 한 번 잴 때 평균 낼 횟수
WTEST_INTERVAL = 0.04     # 측정 간격 (s) -> 25번이면 약 1초
WTEST_SETTLE_SEC = 1.0    # 각 단계 전에 기다리는 시간 (s)


def _fz_stats(motions, label: str) -> float:
    """WTEST_SETTLE_SEC 기다린 뒤 Fz를 WTEST_SAMPLES번 재서 평균 / 흔들림 출력. 평균 반환."""
    motions.wait(WTEST_SETTLE_SEC)
    vals = []
    for _ in range(WTEST_SAMPLES):
        vals.append(float(motions.get_tool_force(motions.DR_BASE)[2]))
        motions.wait(WTEST_INTERVAL)
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    print(f'  [{label}] Fz 평균 {mean:+.3f}N  흔들림(표준편차) {sd:.3f}N  '
          f'최소 {min(vals):+.3f} 최대 {max(vals):+.3f}  ({len(vals)}번)')
    return mean


def weight_test(motions, put_back: bool = True) -> None:
    """(적재대 잡는 위치, 그리퍼 열린 상태에서) 무게 감지 시험.

    닫기 전 Fz -> 그리퍼 닫기 -> 닫은 뒤 Fz -> +Z LIFT_Z_MM 들기 -> 든 뒤 Fz
    각 단계 WTEST_SETTLE_SEC 기다린 뒤 WTEST_SAMPLES번 평균. 끝나면 (put_back) 다시 내려놓고 그리퍼 열기.
    """
    start = _current_x()
    print(f'[wtest] 시작 위치 {[round(v, 1) for v in start[:3]]}  '
          f'(각 단계 {WTEST_SETTLE_SEC:.1f}초 대기 후 {WTEST_SAMPLES}번 평균)')
    before = _fz_stats(motions, '1 닫기 전')
    motions.grip_close()
    closed = _fz_stats(motions, '2 닫은 뒤')
    lifted_x = list(start)
    lifted_x[2] += motions.LIFT_Z_MM
    motions.movel(motions.posx(*lifted_x), vel=motions.INSERT_VELX, acc=motions.INSERT_ACCX)
    lifted = _fz_stats(motions, f'3 {motions.LIFT_Z_MM:.0f}mm 든 뒤')
    print(f'[wtest] 차이: 닫은 뒤-닫기 전 {closed - before:+.3f}N | '
          f'든 뒤-닫은 뒤 {lifted - closed:+.3f}N (판재 무게만) | '
          f'든 뒤-닫기 전 {lifted - before:+.3f}N (지금 load1 판정 방식, 기준 |{motions.WEIGHT_THRESHOLD_N}|N)')
    if put_back:
        motions.movel(motions.posx(*start), vel=motions.INSERT_VELX, acc=motions.INSERT_ACCX)
        motions.grip_open()
        print('[wtest] 제자리로 내리고 그리퍼 열기 -> 다시 wtest 가능')


def weight_test_same_height(motions, put_back: bool = True) -> None:
    """(적재대 잡는 위치, 그리퍼 열린 상태에서) 같은 높이 비교 무게 시험.

    ① 그리퍼 닫기 -> +Z LIFT_Z_MM 들어서 Fz (잡고)
    ② 제자리로 내려 그리퍼 열기 (판재 내려놓음) -> 다시 +Z LIFT_Z_MM 올라가서 Fz (빈 기준, 같은 자세)
    -> 잡고 - 빈 기준 = 같은 자세에서 판재 무게만. 판재가 열린 그리퍼에 딸려 올라가지 않게 빈 기준은 내려놓은 뒤에 잰다.
    각 단계 WTEST_SETTLE_SEC 기다린 뒤 WTEST_SAMPLES번 평균. 끝나면 (put_back) 시작 위치로 내려감 (그리퍼 열린 채).
    """
    start = _current_x()
    up = list(start)
    up[2] += motions.LIFT_Z_MM
    v, a = motions.INSERT_VELX, motions.INSERT_ACCX
    print(f'[wtest2] 시작 위치 {[round(x, 1) for x in start[:3]]}  (같은 높이 Z {up[2]:.1f}에서 잡고 / 빈 상태 비교)')
    motions.grip_close()
    motions.wait(WTEST_SETTLE_SEC)
    motions.movel(motions.posx(*up), vel=v, acc=a)
    held = _fz_stats(motions, f'1 잡고 {motions.LIFT_Z_MM:.0f}mm 위')
    motions.movel(motions.posx(*start), vel=v, acc=a)
    motions.grip_open()
    motions.wait(WTEST_SETTLE_SEC)
    motions.movel(motions.posx(*up), vel=v, acc=a)
    empty = _fz_stats(motions, f'2 내려놓고 연 채로 {motions.LIFT_Z_MM:.0f}mm 위 (빈 기준)')
    print(f'[wtest2] 차이 (잡고 - 빈 기준, 같은 자세): {held - empty:+.3f}N')
    if put_back:
        motions.movel(motions.posx(*start), vel=v, acc=a)
        print('[wtest2] 시작 위치로 내려감 (그리퍼 열림) -> 다시 wtest2 가능')


def weigh(motions, put_back: bool = True) -> None:
    """(적재대 잡는 위치, 그리퍼 열린 상태에서) 잡고 +Z LIFT_Z_MM 들어서 Fz만 재서 출력.

    1초 대기 후 WTEST_SAMPLES번 평균. 판재 있을 때 / 없을 때 각각 해서 값을 비교하는 용도.
    끝나면 (put_back) 제자리로 내리고 그리퍼 열기.
    """
    start = _current_x()
    up = list(start)
    up[2] += motions.LIFT_Z_MM
    motions.grip_close()
    motions.movel(motions.posx(*up), vel=motions.INSERT_VELX, acc=motions.INSERT_ACCX)
    _fz_stats(motions, f'잡고 {motions.LIFT_Z_MM:.0f}mm 든 뒤')
    if put_back:
        motions.movel(motions.posx(*start), vel=motions.INSERT_VELX, acc=motions.INSERT_ACCX)
        motions.grip_open()
        print('[weigh] 제자리로 내리고 그리퍼 열기 -> 다시 weigh 가능')


def print_inputs() -> None:
    """로봇 입력 상태를 한 번에 출력 (안 움직임). 그리퍼가 판재를 잡았는지 알려 주는 신호 찾기용.

    컨트롤러 디지털 입력 1~16, 툴 디지털 입력 1~6, 그리퍼 제어 출력 1~2.
    (아날로그 입력은 컨트롤러에 입력 모드가 설정돼 있지 않아 뺐음)
    """
    from DSR_ROBOT2 import get_digital_input, get_digital_output, get_tool_digital_input

    def read(fn, idx):
        try:
            return fn(idx)
        except Exception as exc:  # noqa: BLE001
            return f'에러({exc})'

    di = [read(get_digital_input, i) for i in range(1, 17)]
    tdi = [read(get_tool_digital_input, i) for i in range(1, 7)]
    do = [read(get_digital_output, i) for i in range(1, 3)]
    print('[din] 컨트롤러 디지털 입력 1~16 : ' + ' '.join(f'{i + 1}:{v}' for i, v in enumerate(di)))
    print('[din] 툴 디지털 입력 1~6        : ' + ' '.join(f'{i + 1}:{v}' for i, v in enumerate(tdi)))
    print('[din] 그리퍼 제어 출력 1~2      : ' + ' '.join(f'{i + 1}:{v}' for i, v in enumerate(do))
          + '   (1:1 2:0 = 닫힘, 1:0 2:1 = 열림)')


def _force6_stats(motions, label: str) -> list:
    """WTEST_SETTLE_SEC 기다린 뒤 힘 6개(Fx, Fy, Fz, Mx, My, Mz)를 WTEST_SAMPLES번 평균. 평균 반환."""
    motions.wait(WTEST_SETTLE_SEC)
    total = [0.0] * 6
    for _ in range(WTEST_SAMPLES):
        f = motions.get_tool_force(motions.DR_BASE)
        for i in range(6):
            total[i] += float(f[i])
        motions.wait(WTEST_INTERVAL)
    mean = [v / WTEST_SAMPLES for v in total]
    print(f'  [{label}] Fx {mean[0]:+.3f} Fy {mean[1]:+.3f} Fz {mean[2]:+.3f} N | '
          f'Mx {mean[3]:+.3f} My {mean[4]:+.3f} Mz {mean[5]:+.3f} Nm  ({WTEST_SAMPLES}번 평균)')
    return mean


def tilt_test(motions, deg: float = 3.0) -> None:
    """(잡고 들어 올린 상태에서) 그리퍼 끝 위치 그대로 ry +deg(앞쪽 숙임) -> 판재 끝이 눌리는 힘 확인 -> 원래 자세로.

    숙이기 전 / 숙인 뒤 힘 6개를 1초 대기 후 25번 평균해서 차이 출력. 판재가 있으면 숙일 때 반력이 생김.
    """
    if abs(deg) > 10.0:
        raise ValueError(f'숙이는 각도는 10도까지만 (입력 {deg})')
    print(f'[tilttest] ry {deg:+.1f}도로 숙여 누르는 힘 확인')
    before = _force6_stats(motions, '숙이기 전')
    motions.tilt_ry(deg)
    after = _force6_stats(motions, f'ry {deg:+.1f}도 숙인 뒤')
    d = [after[i] - before[i] for i in range(6)]
    print(f'[tilttest] 차이 (숙인 뒤 - 전): Fx {d[0]:+.3f} Fy {d[1]:+.3f} Fz {d[2]:+.3f} N | '
          f'Mx {d[3]:+.3f} My {d[4]:+.3f} Mz {d[5]:+.3f} Nm')
    motions.tilt_ry(-deg)
    print('[tilttest] 원래 자세로 되돌림')


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
    picked = motions.grip_and_check(motions.poses.START_POS_PICK_X[layer], layer=layer)
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
        'homef': ('홈으로 빠르게 이동 (빈손 속도 EMPTY_VELJ=100, retreat 뒤 빈손일 때만)',
                  lambda a: motions.go_home(fast=True)),
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
        'enter': ('(sd 후) 작업대 [층=1]에 다가가기만: sd 3 -> 다가가기 순서 끝(넣기 전, 1층은 up 10 뒤)에서 멈춤. 그리퍼 그대로',
                  lambda a: motions.approach_sd(int(a[0]) if a else 1)),
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
        'tilttest': ('[힘 시험] (잡고 든 상태) ry [도=3]만큼 앞쪽 숙여서 판재 끝 누르는 힘(Fx~Mz) 확인 -> 원래 자세로',
                     lambda a: tilt_test(motions, float(a[0]) if a else 3.0)),
        'din': ('[신호 확인] 디지털 입력(컨트롤러 1~16, 툴 1~6) / 그리퍼 출력 상태 출력 (안 움직임)',
                lambda a: print_inputs()),
        'weigh': ('[무게 시험] (적재대 잡는 위치, 그리퍼 열림) 잡고 30mm 들어서 Fz만 출력 (1초 대기 후 25번 평균) '
                  '-> 내려놓고 열기 [keep = 든 채로 두기]',
                  lambda a: weigh(motions, put_back=not (a and a[0].lower() == 'keep'))),
        'wtest': ('[무게 시험] (적재대 잡는 위치, 그리퍼 열림) 닫기 전 / 닫은 뒤 / 든 뒤 Fz를 1초 대기 후 25번 평균 -> '
                  '차이 출력 -> 다시 내려놓고 열기 [keep = 든 채로 두기]',
                  lambda a: weight_test(motions, put_back=not (a and a[0].lower() == 'keep'))),
        'wtest2': ('[무게 시험] 같은 높이 비교: 닫고 30mm 들어 Fz -> 내려놓고 열기 -> 빈 채로 30mm 위 Fz(빈 기준) -> 차이 '
                   '-> 시작 위치로 내려감 [keep = 30mm 위에 두기]',
                   lambda a: weight_test_same_height(motions, put_back=not (a and a[0].lower() == 'keep'))),
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
