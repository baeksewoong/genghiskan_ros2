#!/usr/bin/env bash
# run.sh + ROS2 조인트 스트리머까지 띄워서, 티칭 팬던트 페이지의 3D 로봇팔이
# 실제 로봇 동작을 실시간으로 따라가는 걸 바로 볼 수 있게 하는 실행 스크립트.
#
# - Docker 컨테이너(MySQL)가 안 떠있으면 띄움
# - 백엔드(FastAPI) 실행
# - 이 머신에 ROS2(Jazzy)가 설치돼 있으면: 두산/OnRobot 언더레이 소싱 →
#   sfarm_joint_streamer 패키지 빌드(필요 시) → 조인트 스트리머 노드 실행
#   (ROS2가 없는 머신이면 이 단계는 건너뛰고 경고만 남김 — 백엔드/프론트는 정상 실행)
# - 프론트엔드(Vite) 실행 + 티칭 팬던트 페이지를 브라우저로 자동 오픈
#
# 처음 실행하기 전에는 ./scripts/setup.sh 를 먼저 실행해야 합니다.
# ROS2 쪽까지 쓰려면 app/ros2_ws/src/sfarm_joint_streamer/.env 에
# BACKEND_ROBOT_WS_URL / ROBOT_WS_TOKEN 이 설정돼 있어야 하고(README 참고),
# 이 토큰은 app/backend/.env 의 ROBOT_STATE_WS_TOKEN 과 동일해야 합니다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/.." && pwd)"
RUN_DIR="$APP_DIR/.run"
mkdir -p "$RUN_DIR"

log() { printf '\n\033[1;34m[run]\033[0m %s\n' "$1"; }
warn() { printf '\n\033[1;33m[run][WARN]\033[0m %s\n' "$1" >&2; }
err() { printf '\n\033[1;31m[run][ERROR]\033[0m %s\n' "$1" >&2; }

if [ ! -d "$APP_DIR/backend/.venv" ] || [ ! -d "$APP_DIR/frontend/node_modules" ]; then
  err "아직 설정이 안 된 것 같습니다. 먼저 ./scripts/setup.sh 를 실행해 주세요."
  exit 1
fi

# --- Docker (MySQL) 기동 확인 ---
if ! docker info >/dev/null 2>&1; then
  err "Docker가 실행 중이지 않습니다. Docker Desktop을 먼저 켜 주세요."
  exit 1
fi

mysql_running() {
  (cd "$APP_DIR" && docker compose ps mysql --status running --format '{{.Name}}' 2>/dev/null | grep -q .)
}

ensure_alembic_version_width() {
  # run.sh 참고: alembic_version.version_num 길이 제한으로 인한 재발 문제 방지.
  (cd "$APP_DIR" && docker compose exec -T mysql mysql -uroot -proot printshop -e "
    ALTER TABLE alembic_version MODIFY version_num VARCHAR(255) NOT NULL;
  ") >/dev/null 2>&1 || true
}

if mysql_running; then
  log "MySQL 컨테이너가 이미 떠있습니다."
else
  log "MySQL 컨테이너가 안 떠있어서 기동합니다 (docker compose up -d mysql)"
  (cd "$APP_DIR" && docker compose up -d mysql)
  tries=0
  until (cd "$APP_DIR" && docker compose exec -T mysql mysqladmin ping -h localhost -u root -proot >/dev/null 2>&1); do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
      err "MySQL이 60초 내에 준비되지 않았습니다. 'docker compose logs mysql'로 확인해 주세요."
      exit 1
    fi
    sleep 1
  done
  log "MySQL 준비 완료"
fi

# --- 백그라운드 프로세스 정리 ---
PIDS=()
cleanup() {
  log "종료 중... 백그라운드 프로세스를 정리합니다."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

# --- 백엔드 ---
log "백엔드를 실행합니다 (http://localhost:8000, 로그: .run/backend.log)"
ensure_alembic_version_width
(
  cd "$APP_DIR/backend"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  alembic upgrade head
  exec uvicorn app.main:app --reload --port 8000
) >"$RUN_DIR/backend.log" 2>&1 &
BACKEND_PID="$!"
PIDS+=("$BACKEND_PID")

log "백엔드 기동을 확인하는 중..."
tries=0
while true; do
  if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    err "백엔드가 기동 중 종료됐습니다. 로그를 확인해 주세요 ($RUN_DIR/backend.log):"
    tail -n 30 "$RUN_DIR/backend.log" >&2
    exit 1
  fi
  if curl -s -o /dev/null "http://localhost:8000/docs" 2>/dev/null; then
    log "백엔드 기동 완료"
    break
  fi
  tries=$((tries + 1))
  if [ "$tries" -gt 30 ]; then
    err "백엔드가 30초 내에 기동되지 않았습니다. 로그를 확인해 주세요 ($RUN_DIR/backend.log):"
    tail -n 30 "$RUN_DIR/backend.log" >&2
    exit 1
  fi
  sleep 1
done

# --- ROS2 조인트 스트리머 (실물 로봇 → 3D 뷰어 실시간 추종) ---
ROS2_WS="$APP_DIR/ros2_ws"
JOINT_STREAMER_PKG="sfarm_joint_streamer"
ROS2_ENV_SCRIPT="$REPO_ROOT/.claude/skills/ros2-workspace-ops/scripts/ros2_env.sh"

if [ -f "/opt/ros/jazzy/setup.bash" ] && [ -f "$ROS2_ENV_SCRIPT" ]; then
  log "ROS2 환경을 소싱합니다 (두산/OnRobot 언더레이 -> app/ros2_ws)"
  # shellcheck disable=SC1091
  source "$ROS2_ENV_SCRIPT"

  if [ ! -d "$ROS2_WS/install/$JOINT_STREAMER_PKG" ]; then
    log "조인트 스트리머 패키지를 빌드합니다 (colcon build --packages-select $JOINT_STREAMER_PKG)"
    (cd "$ROS2_WS" && colcon build --symlink-install --packages-select "$JOINT_STREAMER_PKG") \
      || warn "colcon build 실패 — 조인트 스트리밍 없이 계속합니다. 3D 뷰어는 조그 결과만 반영합니다."
  fi
  if [ -f "$ROS2_WS/install/setup.bash" ]; then
    # shellcheck disable=SC1091
    source "$ROS2_WS/install/setup.bash"
  fi

  JOINT_STREAMER_ENV="$ROS2_WS/src/$JOINT_STREAMER_PKG/.env"
  if [ -f "$JOINT_STREAMER_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$JOINT_STREAMER_ENV"
    set +a
  else
    warn "$JOINT_STREAMER_ENV 가 없습니다 — ROBOT_WS_TOKEN이 비어있으면 백엔드가 연결을 거부합니다."
  fi

  if ros2 pkg prefix "$JOINT_STREAMER_PKG" >/dev/null 2>&1; then
    log "조인트 스트리머 노드를 실행합니다 (로그: .run/joint_streamer.log)"
    (exec ros2 run "$JOINT_STREAMER_PKG" joint_streamer) >"$RUN_DIR/joint_streamer.log" 2>&1 &
    JOINT_STREAMER_PID="$!"
    PIDS+=("$JOINT_STREAMER_PID")
  else
    warn "$JOINT_STREAMER_PKG 빌드 결과를 못 찾았습니다 — 조인트 스트리밍 없이 계속합니다."
  fi
else
  warn "이 머신에는 ROS2(Jazzy)가 설치되어 있지 않은 것 같습니다 — 3D 뷰어는 조그 결과만 반영하고, 실시간 로봇 추종은 비활성 상태로 뜹니다."
fi

# --- 프론트엔드 + 티칭 팬던트 페이지 자동 오픈 ---
FRONTEND_URL="http://localhost:5173/#/teaching-pendant"

open_browser_when_ready() {
  local url="$1"
  local tries=0
  until curl -s -o /dev/null "http://localhost:5173" 2>/dev/null; do
    tries=$((tries + 1))
    [ "$tries" -gt 30 ] && return 0
    sleep 1
  done
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi
}

open_browser_when_ready "$FRONTEND_URL" &
PIDS+=("$!")

log "프론트엔드를 실행합니다 ($FRONTEND_URL)"
log "종료하려면 Ctrl+C 를 누르세요 (백엔드/ROS2 노드도 함께 종료됩니다)"
cd "$APP_DIR/frontend"
npm run dev
