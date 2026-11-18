#!/usr/bin/env bash
# 클론 이후 매번 쓰는 실행 스크립트.
# - Docker 컨테이너(MySQL)가 안 떠있으면 띄움
# - 백엔드(FastAPI), 프론트엔드(Vite)를 실행
# 처음 실행하기 전에는 ./scripts/setup.sh 를 먼저 실행해야 합니다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$APP_DIR/.run"
mkdir -p "$RUN_DIR"

log() { printf '\n\033[1;34m[run]\033[0m %s\n' "$1"; }
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
  # alembic_version.version_num은 기본 VARCHAR(32)라서 길이가 32자를 넘는
  # revision id(예: 0009_drop_task_type_event_direction, 36자)를 못 담는다.
  # MySQL DDL은 즉시 커밋되므로, alembic이 해당 revision의 DROP/ALTER를
  # 실행한 뒤 version_num 기록에서 "Data too long"으로 실패하면 — 스키마는
  # 이미 바뀌었는데 alembic_version은 이전 revision에 머물러서, 다음
  # `alembic upgrade head`가 같은 마이그레이션을 또 실행하다 깨진다.
  # 매번 실행 전에 넓혀서(idempotent) 이 문제가 재발하지 않게 한다.
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

# --- 백엔드를 백그라운드로, 프론트엔드를 포그라운드로 실행 ---
PIDS=()

cleanup() {
  log "종료 중... 백엔드 프로세스를 정리합니다."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

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

# 백엔드가 뜨는 걸 확인하기 전에 프론트엔드를 띄우면, (예: alembic 실패로)
# 백엔드가 죽어도 vite가 "ws proxy ECONNREFUSED" 같은 알아보기 힘든 에러만
# 내고 넘어가서 원인을 바로 알 수 없다. 포트가 열리거나 백엔드 프로세스가
# 죽을 때까지 기다렸다가, 죽었으면 로그를 보여주고 바로 중단한다.
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

log "프론트엔드를 실행합니다 (http://localhost:5173)"
log "종료하려면 Ctrl+C 를 누르세요 (백엔드도 함께 종료됩니다)"
cd "$APP_DIR/frontend"
npm run dev
