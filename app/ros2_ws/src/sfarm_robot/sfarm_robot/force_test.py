"""
힘 측정 테스트 (motion_test 메뉴에서만 사용, 액션에서는 안 씀).

가이드(레일)에 밀 때 받는 힘을 눈으로 확인해서 motions.py의 기준값
(WIGGLE_CONTACT_N, DONE_REACT_N, JAM_FORCE_N 등)을 맞추기 위한 도구.
그리퍼는 건드리지 않는다.

  fmon     [초=10]                       : 그 자리에서 힘만 계속 출력 (안 움직임)
  pushtest [축=x] [mm=20] [step=2]        : 순응 제어로 한 축 방향으로 step씩 밀며 매 step 힘 출력
                                           (mm가 -면 반대 방향, 축은 x / y / z)

pushtest 안전장치: 힘 변화가 MAX_FORCE_N 이상이거나 목표보다 MAX_LAG_MM 이상 덜 가면 멈춤.
끝나면 순응 해제(그 자리 고정). 시작 위치로 되돌아가지 않는다.

주의: motions.py처럼 DSR_ROBOT2를 맨 위에서 import 하므로 DR_init 설정 후에 import 해야 한다.
"""
from __future__ import annotations

from DR_common2 import posx
from DSR_ROBOT2 import (
    DR_BASE,
    get_current_posx,
    get_tool_force,
    movel,
    release_compliance_ctrl,
    task_compliance_ctrl,
    wait,
)

PUSH_VELX, PUSH_ACCX = 10.0, 10.0      # 밀 때 속도
# 순응 강성 (N/m). 미는 축만 무르게(500 = 0.5N/mm) 하고 나머지는 단단하게.
SOFT_STX, HARD_STX = 500, 3000
ROT_STX = 200
MAX_FORCE_N = 15.0     # 힘 변화가 이 값 이상이면 멈춤 (안전)
MAX_LAG_MM = 10.0      # 목표보다 이만큼 이상 덜 가면(막힘) 멈춤
SAMPLES = 3            # 한 번 잴 때 평균 낼 횟수
SAMPLE_INTERVAL = 0.05  # 측정 간격 (s)
SETTLE_SEC = 0.3       # 이동 후 재기 전 기다리는 시간 (s)

_AXIS = {'x': 0, 'y': 1, 'z': 2}


def read_force(samples: int = SAMPLES) -> list:
    """베이스 기준 툴 외력 [Fx, Fy, Fz](N) 평균."""
    total = [0.0, 0.0, 0.0]
    for _ in range(samples):
        f = get_tool_force(DR_BASE)
        for i in range(3):
            total[i] += float(f[i])
        wait(SAMPLE_INTERVAL)
    return [v / samples for v in total]


def _fmt(f: list, base: list) -> str:
    d = [f[i] - base[i] for i in range(3)]
    return (f'dFx={d[0]:+6.2f} dFy={d[1]:+6.2f} dFz={d[2]:+6.2f} N   '
            f'(원값 Fx={f[0]:+6.1f} Fy={f[1]:+6.1f} Fz={f[2]:+6.1f})')


def fmon(sec: float = 10.0, period: float = 0.2) -> None:
    """그 자리에서 sec초 동안 힘 변화를 계속 출력 (로봇은 안 움직임). 시작할 때 값이 기준(0)."""
    base = read_force()
    print(f'[fmon] {sec:.0f}초 동안 출력 (기준 Fx={base[0]:.1f} Fy={base[1]:.1f} Fz={base[2]:.1f}N)')
    t = 0.0
    peak = [0.0, 0.0, 0.0]
    while t < sec:
        f = read_force(1)
        for i in range(3):
            peak[i] = max(peak[i], abs(f[i] - base[i]))
        print(f'  {t:5.1f}s  {_fmt(f, base)}')
        wait(period)
        t += period + SAMPLE_INTERVAL
    print(f'[fmon] 최대 변화 |dFx|={peak[0]:.2f} |dFy|={peak[1]:.2f} |dFz|={peak[2]:.2f} N')


def pushtest(axis: str = 'x', mm: float = 20.0, step: float = 2.0) -> None:
    """순응 제어 켜고 지금 위치에서 axis 방향으로 mm만큼 step씩 밀며 매번 힘/위치 출력. 그리퍼 그대로."""
    if axis not in _AXIS:
        raise ValueError(f'축은 x / y / z 중 하나 (입력: {axis})')
    if step <= 0:
        raise ValueError('step은 0보다 커야 함')
    i = _AXIS[axis]
    sign = 1.0 if mm >= 0 else -1.0
    total = abs(mm)

    start = list(get_current_posx()[0])
    wait(SETTLE_SEC)
    base = read_force()
    stx = [HARD_STX, HARD_STX, HARD_STX, ROT_STX, ROT_STX, ROT_STX]
    stx[i] = SOFT_STX
    print(f'[pushtest] {axis.upper()} {sign * total:+.1f}mm, {step:.1f}mm씩, 강성 {stx[:3]}N/m, '
          f'안전: |dF|>={MAX_FORCE_N}N 또는 {MAX_LAG_MM}mm 덜 가면 멈춤')
    print(f'  시작 {[round(v, 1) for v in start[:3]]}  기준 Fx={base[0]:.1f} Fy={base[1]:.1f} Fz={base[2]:.1f}N')

    peak = [0.0, 0.0, 0.0]
    task_compliance_ctrl(stx=stx)
    try:
        wait(0.3)
        pushed = 0.0
        while pushed < total - 1e-9:
            pushed = min(pushed + step, total)
            target = list(start)
            target[i] += sign * pushed
            movel(posx(*target), vel=PUSH_VELX, acc=PUSH_ACCX)
            wait(SETTLE_SEC)
            f = read_force()
            cur = float(get_current_posx()[0][i])
            lag = abs(target[i] - cur)
            d = [f[k] - base[k] for k in range(3)]
            for k in range(3):
                peak[k] = max(peak[k], abs(d[k]))
            print(f'  [{sign * pushed:+5.1f}mm] {axis.upper()}={cur:7.1f} (덜 감 {lag:4.1f}mm)  {_fmt(f, base)}')
            if max(abs(v) for v in d) >= MAX_FORCE_N:
                print(f'  -> 힘 {MAX_FORCE_N}N 넘음, 멈춤')
                break
            if lag >= MAX_LAG_MM:
                print(f'  -> {MAX_LAG_MM}mm 넘게 덜 감 (막힘), 멈춤')
                break
    finally:
        release_compliance_ctrl()   # 지금 위치에서 위치 제어로 고정
    print(f'[pushtest] 끝 (순응 해제, 그 자리 고정). 최대 변화 '
          f'|dFx|={peak[0]:.2f} |dFy|={peak[1]:.2f} |dFz|={peak[2]:.2f} N')
