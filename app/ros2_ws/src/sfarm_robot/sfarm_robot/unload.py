"""
3D 프린터 언로드 작업 (두산 M0609) - 단독 실행 / 개발용.

액션 서버 / 브리지 없이 이 파일만으로 로봇을 움직여 언로드 동작을 만들고 테스트한다.
동작이 완성되면 motions.py의 run_unload()로 옮기면 액션 서버에서도 그대로 쓸 수 있다.

사용법
  ros2 run sfarm_robot unload            # 메뉴에서 골라서 실행 (반복)
  ros2 run sfarm_robot unload step 1     # 바로 실행: 1번 좌표(홈)로 이동
  ros2 run sfarm_robot unload run        # 한 단계씩 (Enter 진행 / b 전 단계 / g 잡기 / r 놓기 / q 멈춤). 진입전2에서 언로드 층 3/2/1 선택
  ros2 run sfarm_robot unload back       # 지금 단계에서 한 단계씩 거꾸로 (back 3 = 3번까지만)
  ros2 run sfarm_robot unload pose      # 현재 위치 좌표 출력

주의: 액션 서버(robot_action_server) / motion_test와 동시에 로봇을 움직이지 말 것.
"""
import importlib
import sys

import DR_init
import rclpy

ROBOT_ID = 'dsr01'
ROBOT_MODEL = 'm0609'

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


# ---------------------------------------------------------------- 속도 (테스트용: 느리게)
# 동작이 검증되면 올린다. 단위: movej = deg/s, movel = mm/s
UNLOAD_VELJ, UNLOAD_ACCJ = 22.5, 22.5
UNLOAD_VELX, UNLOAD_ACCX = 67.5, 67.5

# 언로드 층에 도착한 뒤 잡기 전에 기다리는 시간 (s)
UNLOAD_ARRIVE_WAIT_SEC = 1.0

# 그리퍼를 닫은 뒤 안정시키려 기다리는 시간 (s). 닫는 동작(motions.grip_close) 자체도 1.5초 기다린다.
# (zforce 디버깅에서 힘을 재기 전 대기에도 쓴다)
UNLOAD_SETTLE_SEC = 1.0

# ---------------------------------------------------------------- 잡은 뒤 당겨서 확인 (턱에 걸리는 힘)
# 잡은 상태에서 -X로 UNLOAD_PULL_POS_MM 만큼 위치 제어로 당긴 뒤, 거기서 UNLOAD_PULL_COMPLIANCE_MM를
# 순응 제어로 UNLOAD_PULL_STEP_MM씩 더 가며 힘을 잰다. X 방향 힘 변화가 UNLOAD_CATCH_FORCE_N 이상이면
# 턱에 걸린 것 = 판을 잡음. 끝까지 당겨도 힘이 안 들어오면 못 잡은 것 -> 원위치로 되돌아가 그리퍼를 연다.
UNLOAD_PULL_POS_MM = 160.0          # 위치 제어로 당기는 거리 (-X, mm)
UNLOAD_PULL_COMPLIANCE_MM = 10.0    # 그 뒤 순응 제어로 더 당기는 거리 (mm)
UNLOAD_PULL_VELX, UNLOAD_PULL_ACCX = 30.0, 30.0   # 당길 때 속도 (mm/s)
UNLOAD_PULL_STEP_MM = 5.0           # 순응 구간에서 끊어 가는 거리 (mm)
UNLOAD_CATCH_FORCE_N = 0.7          # X 방향 힘 변화가 이 값(N) 이상이면 턱에 걸림 (실측 후 조정)
UNLOAD_PULL_FORCE_SAMPLES = 3       # 힘 측정 평균 횟수
UNLOAD_PULL_REACH_TOL_MM = 3.0      # 위치 제어 이동 후 목표에 이만큼 이내로 못 가면 오류 (NOT REACHABLE 등)


# ---------------------------------------------------------------- 언로드 동작
# 좌표는 poses.UNLOAD_J = {번호: (이름, posj)}. 동작은 번호 하나씩 만들어 step N으로 테스트한다.
# TODO: 좌표가 모이면 한 번에 이어서 실행하는 run 동작으로 묶고, 완성되면 motions.run_unload()로 옮긴다.
def move_step(motions, n: int) -> None:
    """UNLOAD_J[n] 좌표로 관절 이동 (느린 속도)."""
    motions.unload_move_step(n, log=print)


def list_steps(motions) -> None:
    for n, (name, j) in sorted(motions.poses.UNLOAD_J.items()):
        print(f'  {n}. {name:<12} {j}')


def move_pre(motions, layer: int) -> None:
    """층 진입전 좌표로 관절 이동 (없는 층이거나 진입전2와 같은 좌표면 건너뜀)."""
    motions.unload_move_pre(layer, log=print)


def enter_layer(motions, layer: int) -> None:
    """진입전2 -> (층 진입전) -> 언로드 layer층."""
    motions.unload_enter_layer(layer, log=print)


def leave_layer(motions, layer: int) -> None:
    """언로드 layer층 -> (층 진입전) -> 진입전2."""
    motions.unload_leave_layer(layer, log=print)


def grab_pull(motions, layer: int) -> bool:
    """베드판을 잡고 -X로 당겨 턱에 걸리는 힘이 들어오는지 확인. 잡았으면 True (당겨진 위치에서 멈춤)."""
    return motions.unload_grab_pull(layer, log=print)


def gripper_key(motions, ans: str) -> bool:
    """run 중 그리퍼 입력 처리: g = 잡기(닫기), r = 놓기(열기). 처리했으면 True."""
    if ans == 'g':
        print('  그리퍼 닫기 (잡기)')
        motions.grip_close()
        return True
    if ans == 'r':
        print('  그리퍼 열기 (놓기)')
        motions.grip_open()
        return True
    return False


def run_steps(motions, start: int = 1, end: int | None = None) -> None:
    """등록된 좌표를 번호 순서대로 한 단계씩 이동.

    각 단계 앞에서: Enter = 이 단계로 진행, b = 전 단계로 되돌아감, g = 그리퍼 잡기, r = 그리퍼 놓기, q = 멈춤.
    진입전2(UNLOAD_BRANCH_FROM)에 도착하면 언로드 층(3/2/1)을 골라 그 층으로 간다.
      (UNLOAD_PRE_J에 있는 층(1, 3)은 진입전2 -> 층 진입전 -> 층, 나올 때는 반대)
      - 층 번호 입력 = 진입전2에서 그 층으로 이동 (다른 층으로 바꿀 때는 진입전2를 거침)
      - b = (층에 있으면) 진입전2로 복귀 / (진입전2에 있으면) 전 단계로
    범위에 진입전2가 안 들어가면(예: run 4 6) 그냥 번호 순서대로 진행한다.
    """
    p = motions.poses
    table = p.UNLOAD_J
    layers = getattr(p, 'UNLOAD_LAYER_STEP', {})
    frm = getattr(p, 'UNLOAD_BRANCH_FROM', None)
    branch = bool(layers) and frm in table and start <= frm and (end is None or end >= frm)
    if branch:
        nums = [n for n in sorted(table) if start <= n <= frm]
    else:
        nums = [n for n in sorted(table) if n >= start and (end is None or n <= end)]
    if not nums:
        raise ValueError(f'실행할 좌표 없음 (등록: {sorted(table)})')

    def try_grab(layer: int) -> bool:
        """도착 -> 1초 대기 -> 잡고 -X로 당겨 턱 확인 (grab_pull). 잡았으면 SUCCESS 후 그 자리에서 다음 동작 대기.
        못 잡았으면 FAIL, 원위치로 돌아와 그리퍼 열림."""
        print(f'  언로드{layer} 도착 -> {UNLOAD_ARRIVE_WAIT_SEC:.0f}초 대기 후 잡기')
        motions.wait(UNLOAD_ARRIVE_WAIT_SEC)
        if grab_pull(motions, layer):
            print(f'  [SUCCESS] 언로드{layer} 베드판 잡음 (턱에 걸리는 힘 감지) -> 다음 동작 대기')
            return True
        print(f'  [FAIL] 언로드{layer} 베드판 못 잡음 (턱에 걸리는 힘 없음) -> 원위치로 복귀, 그리퍼 열림')
        return False

    i = 0              # nums[i] = 다음에 갈 단계 (로봇은 nums[i-1]에 있음)
    at_layer = None    # 층을 골라 들어가 있으면 그 층 번호 (3/2/1)
    while True:
        if i < len(nums):
            n = nums[i]
            name, j = table[n]
            ans = input(f'  [{n}] {name} {j} 로 이동할까요? (Enter=진행, b=전 단계, g=잡기, r=놓기, q=멈춤) ').strip().lower()
            if ans == 'q':
                print(f'  {n}번 앞에서 멈춤')
                return
            if gripper_key(motions, ans):
                continue
            if ans == 'b':
                if i < 2:
                    print('  되돌아갈 전 단계가 없음 (지금이 시작 위치)')
                    continue
                i -= 1
                move_step(motions, nums[i - 1])  # 로봇을 한 단계 전으로, 다음 목표는 nums[i]
                continue
            move_step(motions, n)
            i += 1
            continue

        if not branch:
            print('  모든 단계 완료')
            return

        # 진입전2 도착: 언로드 층 선택
        opts = '/'.join(str(k) for k in sorted(layers, reverse=True))
        where = f'언로드{at_layer}' if at_layer else table[frm][0]
        ans = input(f'  [{where}] 갈 언로드 층 ({opts}) 입력 (b=전 단계, c=다시 잡기+당기기, g=잡기, r=놓기, q=멈춤) ').strip().lower()
        if ans == 'q':
            print('  멈춤')
            return
        if gripper_key(motions, ans):
            continue
        if ans == 'c':
            if at_layer is None:
                print('  언로드 층에 있을 때만 가능 (층 번호로 먼저 이동)')
            else:
                try_grab(at_layer)   # 원위치(층 좌표)에서 다시 잡고 당기기
            continue
        if ans == 'b':
            if at_layer is not None:
                leave_layer(motions, at_layer)
                at_layer = None
            elif i < 2:
                print('  되돌아갈 전 단계가 없음')
            else:
                i -= 1
                move_step(motions, nums[i - 1])
            continue
        if ans.isdigit() and int(ans) in layers:
            target = int(ans)
            if at_layer == target:
                print(f'  이미 언로드{ans}에 있음')
                continue
            if at_layer is not None:
                leave_layer(motions, at_layer)  # 층에서 층으로 바로 가지 않고 진입전2를 거침
            enter_layer(motions, target)
            at_layer = target
            if not try_grab(target):
                pass   # 못 잡음: 원위치로 돌아와 그리퍼 열림 상태. at_layer는 그 층 그대로 (c = 다시 시도, b = 진입전2로)
            continue
        print(f'  입력 오류: {opts} 중 하나, b, c, g, r, q')


STEP_MATCH_TOL_DEG = 3.0   # 현재 관절각이 좌표와 이 값 이내면 '그 단계에 있음'으로 본다


def current_step(motions) -> int | None:
    """지금 로봇이 있는 단계 번호 (UNLOAD_J 좌표와 가장 가까운 것, 허용 오차 밖이면 None)."""
    cur = motions.get_current_poses()[0]
    best = None
    for n, (_name, j) in motions.poses.UNLOAD_J.items():
        err = max(abs(cur[i] - j[i]) for i in range(6))
        if err <= STEP_MATCH_TOL_DEG and (best is None or err < best[0]):
            best = (err, n)
    return best[1] if best else None


def back_steps(motions, to: int = 1) -> None:
    """지금 단계에서 to번 단계까지 왔던 길을 거꾸로, 한 단계씩 되돌아감 (Enter=진행, q=멈춤)."""
    cur = current_step(motions)
    if cur is None:
        raise ValueError('지금 위치가 어느 단계 좌표와도 맞지 않음 -> `step N`으로 직접 이동하세요')
    if to >= cur:
        raise ValueError(f'지금 {cur}번 단계: {to}번은 뒤가 아님 (`back N`의 N은 {cur}보다 작아야 함)')
    table = motions.poses.UNLOAD_J
    print(f'  현재 {cur}번 ({table[cur][0]}) -> {to}번까지 되돌아감')
    for n in range(cur - 1, to - 1, -1):
        if n not in table:
            continue
        name, j = table[n]
        ans = input(f'  [{n}] {name} {j} 로 되돌아갈까요? (Enter=진행, q=멈춤) ')
        if ans.strip().lower() == 'q':
            print(f'  {n}번 앞에서 멈춤')
            return
        move_step(motions, n)
    print('  되돌아가기 완료')


# ---------------------------------------------------------------- 디버깅: 상하 이동 중 힘 로그
ZFORCE_VELX, ZFORCE_ACCX = 20.0, 20.0   # 상하 이동 속도 (mm/s, 느리게)


def zforce_test(motions, up: float = 20.0, down: float = 20.0, step: float = 5.0) -> None:
    """지금 위치(예: 진입전2)에서 Z를 위로 up, 아래로 down(mm)까지 step씩 움직이며 매 위치의 힘을 로그로 남긴다.

    경로: 0 -> +step ... -> +up -> 0 -> -step ... -> -down -> 0 (마지막에 시작 위치로 복귀).
    각 위치에서 UNLOAD_SETTLE_SEC 기다린 뒤 [Fx, Fy, Fz]를 재고, 처음(시작 위치)의 힘 대비 변화를 출력한다.
    그리퍼 상태(열림/닫힘)는 건드리지 않는다. 판을 잡은 채로 하면 무게 변화를 볼 수 있다.
    """
    if step <= 0:
        raise ValueError('step은 0보다 커야 함')
    start = list(motions.get_current_poses()[1])
    cur_step = current_step(motions)
    name = motions.poses.UNLOAD_J[cur_step][0] if cur_step else '단계 좌표 아님'
    print(f'  [힘 디버깅] 시작 위치: {name}  Z={start[2]:.1f}mm  (위 {up:.0f}mm / 아래 {down:.0f}mm, {step:.0f}mm씩, '
          f'속도 {ZFORCE_VELX}mm/s)')

    def goto(dz):
        target = list(start)
        target[2] += dz
        motions.movel(motions.posx(*target), vel=ZFORCE_VELX, acc=ZFORCE_ACCX)

    motions.wait(UNLOAD_SETTLE_SEC)
    base = motions.read_force_xyz()
    print(f'  [힘 디버깅] 기준(시작 위치): Fx={base[0]:+.2f} Fy={base[1]:+.2f} Fz={base[2]:+.2f} N')
    print('  [힘 디버깅]   Z변위(mm)      Fx      Fy      Fz   |   dFx    dFy    dFz')

    def n_steps(total):
        return int(total // step)

    offsets = [step * k for k in range(1, n_steps(up) + 1)] + [0.0] \
        + [-step * k for k in range(1, n_steps(down) + 1)] + [0.0]
    try:
        for dz in offsets:
            goto(dz)
            motions.wait(UNLOAD_SETTLE_SEC)
            f = motions.read_force_xyz()
            d = [f[i] - base[i] for i in range(3)]
            print(f'  [힘 디버깅]   {dz:+8.1f}   {f[0]:+7.2f} {f[1]:+7.2f} {f[2]:+7.2f}   | {d[0]:+6.2f} {d[1]:+6.2f} {d[2]:+6.2f}')
    finally:
        goto(0.0)   # 도중에 멈추거나 오류가 나도 시작 위치로 복귀 시도
    print('  [힘 디버깅] 끝 (시작 위치로 복귀)')


def build_commands(motions):
    """메뉴 이름 -> (설명, 실행 함수(인자 리스트)) 표."""
    return {
        'step': ('좌표 번호 [N=1] 로 이동 (관절 이동, 느리게)',
                 lambda a: move_step(motions, int(a[0]) if a else 1)),
        'steps': ('등록된 좌표 목록 보기', lambda a: list_steps(motions)),
        'run': ('좌표를 [시작=1] [끝] 번호 순서대로 한 단계씩 (Enter=진행, b=전 단계, g=잡기, r=놓기, q=멈춤). 진입전2에서 언로드 층 3/2/1 선택',
                lambda a: run_steps(motions,
                                    int(a[0]) if len(a) > 0 else 1,
                                    int(a[1]) if len(a) > 1 else None)),
        'back': ('지금 단계에서 [N=1]번 단계까지 한 단계씩 거꾸로 되돌아감 (Enter=진행, q=멈춤)',
                 lambda a: back_steps(motions, int(a[0]) if a else 1)),
        'where': ('지금 로봇이 있는 단계 번호 확인',
                  lambda a: print(f'  현재 단계: {current_step(motions)}')),
        'home': ('홈(1번 좌표)으로 이동', lambda a: move_step(motions, 1)),
        'grip': ('그리퍼 닫기', lambda a: motions.grip_close()),
        'release': ('그리퍼 열기', lambda a: motions.grip_open()),
        'pose': ('현재 위치 출력 (좌표 따올 때: posj / posx 복사)',
                 lambda a: print('  posj =', [round(v, 2) for v in motions.get_current_poses()[0]],
                                 '\n  posx =', [round(v, 2) for v in motions.get_current_poses()[1]])),
        'zforce': ('[디버깅] 지금 위치에서 Z를 [위=20] [아래=20] mm까지 [step=5]mm씩 움직이며 힘(Fx,Fy,Fz) 로그',
                   lambda a: zforce_test(motions,
                                         float(a[0]) if len(a) > 0 else 20.0,
                                         float(a[1]) if len(a) > 1 else 20.0,
                                         float(a[2]) if len(a) > 2 else 5.0)),
        'force': ('현재 Fz(N) 측정', lambda a: print(f'  현재 Fz = {motions.read_fz():.2f} N')),
    }


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
    print('\n----- 언로드 -----')
    for i, (name, (desc, _)) in enumerate(commands.items(), 1):
        print(f'  {i}. {name:<9} {desc}')
    print('  q. 종료')


def main(args=None) -> None:
    """Entry point for unload."""
    rclpy.init(args=args)
    node = rclpy.create_node('sfarm_unload', namespace=ROBOT_ID)
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
            run_one(commands, cli[0], cli[1:], logger)
        else:
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
                    importlib.reload(sys.modules[__name__])
                except Exception as exc:  # noqa: BLE001
                    logger.error(f'코드 다시 읽기 실패 (문법 오류?): {exc}')
                    continue
                commands = sys.modules[__name__].build_commands(motions)
                run_one(commands, name, line[1:], logger)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()