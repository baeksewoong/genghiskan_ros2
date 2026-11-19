#!/usr/bin/env bash
# 전체 시스템 실행 스크립트 (ROS 2 + 백엔드 + 프론트엔드).
#
#   1) Doosan 드라이버 (m0609_rg2_bringup)   — 이미 떠있으면 건너뜀
#   2) sfarm_robot robot_action_server        — /sfarm/* 액션 서버
#   3) sfarm_bridge                           — SQS <-> ROS 브릿지
#   4) ./scripts/run.sh                        — MySQL + 백엔드(FastAPI) + 프론트엔드(Vite)
#
# Ctrl+C 한 번이면 위의 프로세스를 전부 정리합니다.
#
# 사용법:
#   ./scripts/run_all.sh                 # 전체 실행 (드라이버 real 모드)
#   ./scripts/run_all.sh --build         # 실행 전에 colcon build
#   ./scripts/run_all.sh --no-driver     # 드라이버는 따로 띄운 경우
#   ./scripts/run_all.sh --ros-only      # 웹(백엔드/프론트) 없이 ROS만
#   ./scripts/run_all.sh --web-only      # ROS 없이 웹만 (= run.sh)
#
# 환경변수로 덮어쓰기:
#   DSR_WS_PATH   (기본 ~/ws_cobot_pjt/ws_dsr)
#   DSR_MODE      (기본 real, 시뮬레이션은 virtual)
#   DSR_HOST      (기본 192.168.1.100)
#   DSR_PORT      (기본 12345)
#   DSR_MODEL     (기본 m0609)
#   ROS_DOMAIN_ID (기본 20)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_WS="$APP_DIR/ros2_ws"
RUN_DIR="$APP_DIR/.run"
mkdir -p "$RUN_DIR"

DSR_WS_PATH="${DSR_WS_PATH:-$HOME/ws_cobot_pjt/ws_dsr}"
DSR_MODE="${DSR_MODE:-real}"
DSR_HOST="${DSR_HOST:-192.168.1.100}"
DSR_PORT="${DSR_PORT:-12345}"
DSR_MODEL="${DSR_MODEL:-m0609}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-20}"

log() { printf '\n\033[1;32m[run_all]\033[0m %s\n' "$1"; }
err() { printf '\n\033[1;31m[run_all][ERROR]\033[0m %s\n' "$1" >&2; }

DRIVER_PGID=""
DO_BUILD=0
RUN_DRIVER=1
RUN_ROS=1
RUN_WEB=1
for arg in "$@"; do
  case "$arg" in
    --build) DO_BUILD=1 ;;
    --no-driver) RUN_DRIVER=0 ;;
    --ros-only) RUN_WEB=0 ;;
    --web-only) RUN_ROS=0 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) err "알 수 없는 옵션: $arg (--help 참고)"; exit 1 ;;
  esac
done

if [ "$RUN_ROS" -eq 0 ]; then
  exec "$SCRIPT_DIR/run.sh"
fi

# --- 프로세스 정리 ---
# 각 ROS 프로세스는 setsid로 별도 프로세스 그룹에서 띄우고, 종료 시 그룹 전체에
# SIGINT → (15초 후에도 살아있으면) SIGKILL 을 보낸다. ros2 launch의 자식 노드까지 정리됨.
PGIDS=()
CLEANED=0
cleanup() {
  [ "$CLEANED" -eq 1 ] && return
  CLEANED=1
  log "종료 중... ROS 프로세스를 정리합니다."
  for pgid in "${PGIDS[@]:-}"; do
    [ -n "$pgid" ] && kill -INT -- "-$pgid" >/dev/null 2>&1 || true
  done
  for _ in $(seq 1 30); do  # 최대 15초: 드라이버가 로봇과의 RT 연결을 정상 해제할 시간
    alive=0
    for pgid in "${PGIDS[@]:-}"; do
      [ -n "$pgid" ] && kill -0 -- "-$pgid" >/dev/null 2>&1 && alive=1
    done
    [ "$alive" -eq 0 ] && break
    sleep 0.5
  done
  for pgid in "${PGIDS[@]:-}"; do
    [ -n "$pgid" ] && kill -KILL -- "-$pgid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# --- ROS 환경 ---
# ~/.bashrc의 ROS_DISCOVERY_SERVER 설정이 남아 있으면 로컬 Doosan 드라이버의
# /dsr01 토픽이 안 보인다. 드라이버와 같은 simple discovery로 맞춘다.
unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT

set +u  # ROS setup 스크립트는 unbound 변수를 참조함
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
if [ -f "$DSR_WS_PATH/install/setup.bash" ]; then
  # shellcheck disable=SC1091
  source "$DSR_WS_PATH/install/setup.bash"
else
  set -u
  err "Doosan 워크스페이스를 찾을 수 없습니다: $DSR_WS_PATH (DSR_WS_PATH로 지정해 주세요)"
  exit 1
fi

if [ "$DO_BUILD" -eq 1 ]; then
  log "colcon build (app/ros2_ws)"
  (cd "$ROS_WS" && colcon build --symlink-install)
fi
if [ ! -f "$ROS_WS/install/setup.bash" ]; then
  set -u
  err "ROS 워크스페이스가 빌드되지 않았습니다. --build 옵션으로 실행해 주세요."
  exit 1
fi
# shellcheck disable=SC1091
source "$ROS_WS/install/setup.bash"
set -u

# start_bg <이름> <명령...> : 백그라운드 실행, 로그는 .run/<이름>.log
start_bg() {
  local name="$1"; shift
  setsid "$@" >"$RUN_DIR/$name.log" 2>&1 &
  local pid="$!"
  PGIDS+=("$pid")
  log "$name 실행 (pid $pid, 로그: .run/$name.log)"
}

# 프로세스가 기동 중에 죽었는지 확인
check_alive() {
  local name="$1" pgid="$2"
  if ! kill -0 -- "-$pgid" >/dev/null 2>&1; then
    err "$name 이(가) 기동 중 종료됐습니다 ($RUN_DIR/$name.log):"
    tail -n 30 "$RUN_DIR/$name.log" >&2
    exit 1
  fi
}

# --- 1) Doosan 드라이버 ---
# /dsr01/joint_states는 joint_state_publisher도 내보내서 드라이버(ros2_control_node)가
# 죽어도 보인다. 실제 로봇 제어 서비스(dsr_controller2/motion/move_line)로 판단한다.
driver_ready() {
  ros2 service list 2>/dev/null | grep -q '^/dsr01/dsr_controller2/motion/move_line$'
}

# 이 스크립트가 띄운 드라이버의 ros2_control_node가 죽었는지 (launch 자체는 계속 살아있음)
driver_died() {
  [ -f "$RUN_DIR/dsr_driver.log" ] &&
    grep -q 'ERROR\] \[ros2_control_node-1\]: process has died' "$RUN_DIR/dsr_driver.log"
}

if [ "$RUN_DRIVER" -eq 1 ]; then
  # launch만 살아있고 실제 드라이버(ros2_control_node)는 죽은 '좀비' 상태면 기다려도 소용없다.
  # 로봇과 연결된 프로세스가 없으므로 강제 종료해도 안전 -> 정리하고 새로 띄운다.
  # (이 상태의 launch는 SIGINT를 무시하는 경우가 있어 SIGTERM, SIGKILL 순으로 보냄)
  if pgrep -f 'ros2 launch m0609_rg2_bringup' >/dev/null 2>&1 &&
     ! pgrep -f 'controller_manager/ros2_control_node' >/dev/null 2>&1; then
    log "드라이버(ros2_control_node)가 죽은 채 남아있는 Doosan launch를 정리합니다."
    for sig in INT TERM KILL; do
      pkill "-$sig" -f 'ros2 launch m0609_rg2_bringup' >/dev/null 2>&1 || true
      for _ in $(seq 1 10); do
        pgrep -f 'ros2 launch m0609_rg2_bringup' >/dev/null 2>&1 || break 2
        sleep 0.5
      done
    done
    # launch가 띄웠던 나머지 노드(rviz, publisher 등)도 정리
    pkill -KILL -f 'm0609_rg2_bringup|__ns:=/dsr01' >/dev/null 2>&1 || true
    log "RT 연결 해제를 위해 10초 대기 후 드라이버를 새로 띄웁니다."
    sleep 10
  fi

  if pgrep -f 'ros2 launch m0609_rg2_bringup' >/dev/null 2>&1; then
    log "Doosan 드라이버가 이미 실행 중입니다. 건너뜁니다."
  else
    start_bg dsr_driver ros2 launch m0609_rg2_bringup bringup.launch.py \
      mode:="$DSR_MODE" host:="$DSR_HOST" port:="$DSR_PORT" model:="$DSR_MODEL"
    DRIVER_PGID="$!"
  fi
fi

log "Doosan 드라이버(/dsr01/dsr_controller2 서비스) 대기 중..."
tries=0
until driver_ready; do
  if [ -n "$DRIVER_PGID" ]; then
    check_alive dsr_driver "$DRIVER_PGID"
    if driver_died; then
      err "Doosan 드라이버(ros2_control_node)가 기동 중 죽었습니다 ($RUN_DIR/dsr_driver.log)."
      grep -v '^\[ros2_control_node-1\] *[#|]' "$RUN_DIR/dsr_driver.log" | grep 'ros2_control_node' | tail -n 15 >&2
      err "로봇 컨트롤러가 이전 RT 연결을 아직 잡고 있을 수 있습니다. 30초쯤 기다렸다 다시 실행하거나, 계속되면 컨트롤러를 재부팅해 주세요."
      exit 1
    fi
  fi
  tries=$((tries + 1))
  if [ "$tries" -gt 60 ]; then
    err "60초 내에 Doosan 드라이버가 준비되지 않았습니다. 로봇 연결/ROS_DOMAIN_ID($ROS_DOMAIN_ID)를 확인해 주세요."
    [ -f "$RUN_DIR/dsr_driver.log" ] && tail -n 30 "$RUN_DIR/dsr_driver.log" >&2
    exit 1
  fi
  sleep 1
done
log "Doosan 드라이버 준비 완료"

# --- 2) 로봇 액션 서버, 3) 브릿지 ---
start_bg robot_action_server ros2 run sfarm_robot robot_action_server
ACTION_PGID="$!"
start_bg sfarm_bridge ros2 run sfarm_bridge sfarm_bridge
BRIDGE_PGID="$!"

sleep 3
check_alive robot_action_server "$ACTION_PGID"
check_alive sfarm_bridge "$BRIDGE_PGID"
log "ROS 노드 기동 완료"

# --- 4) 웹 (MySQL + 백엔드 + 프론트엔드) ---
if [ "$RUN_WEB" -eq 1 ]; then
  # exec 하지 않고 자식으로 실행해야 run.sh 종료 시 여기 cleanup이 ROS도 정리함
  "$SCRIPT_DIR/run.sh"
else
  log "ROS만 실행 중입니다. 종료하려면 Ctrl+C 를 누르세요."
  log "로그 보기: tail -f $RUN_DIR/{robot_action_server,sfarm_bridge}.log"
  wait
fi
