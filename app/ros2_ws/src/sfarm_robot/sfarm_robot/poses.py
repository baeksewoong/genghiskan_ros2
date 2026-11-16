"""
좌표표 (위치 번호 -> 좌표).

로봇 동작 코드는 motions.py, 좌표 값은 여기에만 둔다.
posj: 관절각 [deg] 6개, posx: 위치 [mm] 3개 + 자세 [deg] 3개.

웹(SQS)에서 오는 위치 번호
  - start_pos_id   : 판재 적재대 칸 번호   (Load에서 가져올 곳)
  - pos_3d_id      : 3D 프린터 번호        (Load에서 넣을 곳 / Unload에서 뺄 곳)
  - receive_pos_id : 수령대 칸 번호        (Unload에서 놓을 곳)
백엔드 기준 칸/프린터 번호는 1, 2, 3 이다.
"""

# ---------------------------------------------------------------- 공통 위치
# 홈(대기) 위치 - 동작 시작/끝에 돌아오는 곳
HOME_J = [0, 0, 90, 0, 90, 0]

# ---------------------------------------------------------------- 홈 -> 적재대 경로
# 홈에서 적재대로 갈 때 순서대로 지나가는 경유점 (movej, 관절 좌표 기준)
# move1: 적재대 쪽으로 회전 (높이/자세는 홈과 같음)
MOVE1_J = [-28.91, 6.81, 82.76, 0, 90.46, -28.95]
MOVE1_X = [367.3, -194.9, 424.2, 108.8, 179.9, 108.9]
# move2: 같은 위치에서 그리퍼를 옆으로 눕힘 (적재대에 수평으로 들어가는 자세)
MOVE2_J = [-39.6, -4.6, 133.6, 111.4, 43.2, -178.4]
MOVE2_X = [367.3, -194.9, 424.2, 0.1, 90, 0]

# 적재대 층별 진입 전 위치 (키 = 층 번호): move2에서 내려와서 적재대 앞에 선 지점
BOARD_APPROACH_J = {
    3: [-42.21, 6.82, 124.73, 124.58, 55.67, -141.52],
}
BOARD_APPROACH_X = {
    3: [365.11, -210.62, 295.73, 0.78, 91.32, 0.49],
}

# 적재대 층별 위치 (키 = 층 번호): 진입 전 위치에서 앞으로 들어간 지점. 지금은 3층만 티칭됨.
BOARD_LAYER_J = {
    3: [-32.9, 14.5, 114.8, 133.1, 48.5, -145.4],
}
BOARD_LAYER_X = {
    3: [449.1, -203.9, 295.3, 0.3, 91.4, 0.2],
}

# ---------------------------------------------------------------- 위치 번호별 좌표
# TODO: 실제 티칭한 좌표로 채우기. 키(1, 2, 3)는 웹에서 오는 번호.
# 각 위치마다 'approach'(위에서 접근하는 지점)와 'pick' 또는 'place'(실제로 잡거나
# 놓는 지점)를 posx로 적는다.

# 판재 적재대 (start_pos_id)
BOARD_STOCK = {
    1: {'approach': None, 'pick': None},
    2: {'approach': None, 'pick': None},
    3: {'approach': None, 'pick': None},
}

# 3D 프린터 (pos_3d_id)
PRINTER = {
    1: {'approach': None, 'place': None},
    2: {'approach': None, 'place': None},
    3: {'approach': None, 'place': None},
}

# 수령대 (receive_pos_id)
RECEIVE = {
    1: {'approach': None, 'place': None},
    2: {'approach': None, 'place': None},
    3: {'approach': None, 'place': None},
}


def get_pose(table: dict, pos_id: int, key: str, table_name: str) -> list:
    """좌표표에서 좌표 하나를 꺼낸다. 번호가 없거나 아직 비어 있으면 예외를 던진다.

    예외가 나면 액션 서버가 그 작업을 실패(success=False)로 돌려보내므로,
    좌표가 비어 있는 상태에서 로봇이 엉뚱하게 움직이지 않는다.
    """
    if pos_id not in table:
        raise ValueError(f'{table_name}에 {pos_id}번 위치가 없음 (가능: {list(table)})')
    pose = table[pos_id].get(key)
    if pose is None:
        raise ValueError(f'{table_name}[{pos_id}]["{key}"] 좌표가 아직 비어 있음 (poses.py)')
    return pose
