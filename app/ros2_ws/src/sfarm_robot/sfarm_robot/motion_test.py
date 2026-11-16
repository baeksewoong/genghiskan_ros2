"""
모션 단독 테스트 (액션 서버 / 브리지 없이 motions.py 함수만 바로 실행).

액션 서버가 쓰는 motions.py / poses.py를 그대로 불러와서 실행하므로,
여기서 확인한 동작이 액션 서버에서도 똑같이 나온다.
메뉴 모드에서도 명령마다 motions.py / poses.py를 다시 읽으므로,
파일을 고치고 저장한 뒤 같은 메뉴에서 바로 다시 실행하면 된다 (재시작 불필요).

사용법
  ros2 run sfarm_robot motion_test              # 메뉴에서 골라서 실행 (반복)
  ros2 run sfarm_robot motion_test board 3      # 바로 실행: 홈 -> 적재대 3층
  ros2 run sfarm_robot motion_test board 3 2    # move2(2단계)까지만 가고 멈춤 (3=진입 전, 4=적재대)
  ros2 run sfarm_robot motion_test board_step 3 # 한 단계씩 Enter로 진행
  ros2 run sfarm_robot motion_test load 3 1     # 바로 실행: run_load(start_pos_id=3, pos_3d_id=1)

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


def build_commands(motions):
    """메뉴 이름 -> (설명, 실행 함수(인자 리스트)) 표."""
    from sfarm_interfaces.action import Load, Load1, Unload

    def load1(args):
        s = int(args[0]) if len(args) > 0 else 3
        return motions.run_load1(Load1.Goal(work_id=0, start_pos_id=s))

    def load(args):
        s = int(args[0]) if len(args) > 0 else 3
        p = int(args[1]) if len(args) > 1 else 1
        return motions.run_load(Load.Goal(work_id=0, start_pos_id=s, pos_3d_id=p))

    def unload(args):
        p = int(args[0]) if len(args) > 0 else 1
        r = int(args[1]) if len(args) > 1 else 1
        return motions.run_unload(Unload.Goal(work_id=0, pos_3d_id=p, receive_pos_id=r))

    def check(args):
        # 지금 위치에서 잡고 들어 올려 무게 확인 (적재대 위치에 가 있는 상태에서 사용)
        layer = int(args[0]) if args else 3
        return motions.grip_and_check(motions.poses.BOARD_LAYER_X[layer])

    def leave(args):
        motions.put_back_and_leave(int(args[0]) if args else 3)

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
        'home': ('홈으로 이동', lambda a: motions.go_home()),
        'board': ('홈 -> 적재대 [층=3] [멈출 단계: 0홈 1move1 2move2 3진입전 4적재대]', board),
        'board_step': ('홈 -> 적재대 [층=3] 한 단계씩 (Enter=진행, q=멈춤)', board_step),
        'leave': ('(load/check 후 적재대에 멈춘 상태) 판재 내려놓고 그리퍼 열고 -> 홈 [층=3]', leave),
        'board_home': ('적재대 -> 홈 [층=3]', lambda a: motions.board_to_home(int(a[0]) if a else 3)),
        'pick': ('홈 -> 적재대 -> 잡고 +Z 들기 -> 무게 확인 -> 홈 [층=3]  => True/False',
                 lambda a: motions.pick_from_board(int(a[0]) if a else 3)),
        'check': ('(적재대 위치에서) 잡고 +Z 들기 -> 무게 확인 [층=3]  => True/False', check),
        'force': ('현재 Fz(N) 측정', force),
        'grip': ('그리퍼 닫기', lambda a: motions.grip_close()),
        'release': ('그리퍼 열기', lambda a: motions.grip_open()),
        'load1': ('run_load1 [start_pos_id=3]  => True/False', load1),
        'load': ('run_load [start_pos_id=3] [pos_3d_id=1]  => True/False', load),
        'unload': ('run_unload [pos_3d_id=1] [receive_pos_id=1]', unload),
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
    print('\n----- 모션 테스트 -----')
    for i, (name, (desc, _)) in enumerate(commands.items(), 1):
        print(f'  {i}. {name:<11} {desc}')
    print('  q. 종료')
    print('입력 예: board 3  /  board 3 2  /  board_step 3  /  load 3 1')


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
