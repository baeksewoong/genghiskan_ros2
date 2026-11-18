# app/

웹 서버(FastAPI) + 대시보드(React) + ROS 2 워크스페이스. 백엔드는 레이어드
아키텍처(`api → services → repositories → models/core`), 프론트는 아토믹 디자인
(`atoms → molecules → organisms → templates → pages`)으로 구성했습니다.

로봇과는 AWS SQS로만 통신합니다 — 서버가 `robot-commands` 큐에 명령(load/load2/unload1/unload2,
조그/그리퍼)을 보내고, ROS 2 `sfarm_bridge` 노드가 실행 결과를 `robot-events` 큐로 돌려줍니다.
(PRD: `assets/docs/prd-work-request-sqs.md`, `assets/docs/prd-teaching-pendant.md`)

```
app/
  backend/        FastAPI 서버 (작업요청·적재대·수령대·티칭 팬던트 API, SQS 프로듀서/컨슈머, 출력 타이머, /ws/client)
  frontend/       Vite + React + TS 대시보드 (작업요청, 적재대/프린터/수령대 현황, 알럿, SQS 모니터, 티칭 팬던트)
  ros2_ws/        ROS 2 워크스페이스 (sfarm_interfaces / sfarm_bridge / sfarm_robot)
  docker-compose.yml  MySQL 8.0 + backend
```

## 스크립트로 실행 (권장)

처음 클론받은 뒤 한 번만:

```bash
cd app
./scripts/setup.sh   # venv 생성 + pip/npm install + .env 생성 + MySQL(Docker) 기동 + alembic upgrade head
```

그 이후로는 매번:

```bash
cd app
./scripts/run.sh     # MySQL 컨테이너 안 떠있으면 기동 + 백엔드·프론트엔드 실행
```

- 백엔드: http://localhost:8000, 프론트엔드: http://localhost:5173
- 백엔드 로그는 `app/.run/backend.log`에 쌓입니다.
- 종료는 프론트가 실행 중인 터미널에서 `Ctrl+C` (백엔드도 함께 정리됩니다).
- SQS를 쓰려면 `backend/.env`에 `COMMAND_QUEUE_URL`/`EVENT_QUEUE_URL`과 AWS 자격증명을 넣어야 합니다.
  비워두면 SQS 송수신이 조용히 비활성화됩니다.
- DB를 업장 초기 상태로 되돌리려면:
  `docker compose exec -T mysql mysql -u root -proot printshop < scripts/reset_db.sql`
- 자세한 동작/옵션은 `scripts/setup.sh`, `scripts/run.sh` 주석 참고. Docker가 꺼져 있으면
  Docker Desktop을 먼저 켜야 합니다.

## 전체 실행 (Docker)

```bash
cd app
docker compose up --build
```

- 서버: http://localhost:8000 (기동 시 `alembic upgrade head`로 스키마 반영 후 기동)
- 프론트는 별도로 `cd frontend && npm install && npm run dev` 로 띄웁니다 (http://localhost:5173, `/api`·`/ws`를 8000번으로 proxy).

## 로컬에서 하나씩 실행 (Docker 없이, 스크립트 미사용)

```bash
# 1) 백엔드 (SQLite로 빠르게 — 운영은 MySQL)
cd app/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"
python - <<'EOF'   # SQLite는 이 스크립트로 스키마 생성 (MySQL이면 alembic upgrade head)
import asyncio
from app import models
from app.core.database import Base, engine

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

asyncio.run(main())
EOF
uvicorn app.main:app --reload

# 2) 프론트 (다른 터미널)
cd app/frontend
npm install && npm run dev
```

테스트: `pytest` (backend 디렉터리에서), `npm run build` (frontend 타입체크 겸 빌드).

## 작업 흐름 요약

1. **작업요청** → 적재대 베드 확인 → `load`(베드 집기) 발행 → `success_load1` → 빈 프린터를 골라 `load2`(배치) 발행 → `success_load2` → 출력 타이머 시작
2. **출력 완료** → `unload1`(프린터에서 꺼내기) 발행 → `success_unload1` → 프린터 비움 + 빈 수령대(1번 우선)를 골라 `unload2` 발행 → `success_unload2` → 수령 대기
3. **수령하기** → 수령대 비움 → 수령대가 가득 차서 기다리던 완성품이 있으면 `unload2` 자동 발행
4. 실패(`fail_load1`/`fail_unload1`)나 수령대 가득 참은 대시보드 알럿으로 띄우고, 실패 알럿의 "확인"은 같은 명령을 다시 보낸다.
