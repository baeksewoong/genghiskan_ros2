import asyncio
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
# 로컬 .env에 실제 AWS SQS 큐 URL/자격증명이 들어있을 수 있으므로, 테스트는 절대
# 거기 의존하지 않도록 빈 값으로 덮어써 작업요청(SQS) 컨슈머 루프가 실제 네트워크를
# 타지 않게 한다 (PRD: assets/docs/prd-work-request-sqs.md 7장).
os.environ["COMMAND_QUEUE_URL"] = ""
os.environ["EVENT_QUEUE_URL"] = ""

import pytest
import pytest_asyncio

from app.core.bootstrap import ensure_seed_data
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.runtime import TeachingPendantSession, runtime


@pytest_asyncio.fixture(autouse=True)
async def _fresh_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await ensure_seed_data(session)

    runtime.client_connections.clear()
    # 티칭 팬던트 조그 세션은 테스트마다 항상 비활성으로 시작한다 (PRD:
    # prd-teaching-pendant.md 5장 — 서버 재시작 시 복원하지 않는 설계와 동일하게).
    runtime.teaching_pendant = TeachingPendantSession()

    yield
