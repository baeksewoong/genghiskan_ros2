import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    board_stock,
    receive_pos,
    health,
    orders,
    sqs,
    state,
    stats,
    teaching_pendant,
    work_requests,
)
from app.api.ws import client_ws
from app.core.bootstrap import ensure_seed_data
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.sqs_consumer_service import SqsConsumerService
from app.services.teaching_pendant_service import TeachingPendantService
from app.services.timer_service import TimerService

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as session:
        await ensure_seed_data(session)

    # 루프 범위 변수로 둔다 (모듈 전역이면 lifespan을 여러 번 도는 테스트에서 이전
    # 이벤트 루프의 완료된 태스크가 남아 있다가 asyncio.gather에서 "다른 루프에 속한
    # future" 오류를 낸다).
    background_tasks = [
        asyncio.create_task(TimerService.sweep_loop()),
        # 작업요청(SQS) 경로 전용: event_queue_url 미설정이면 즉시 반환해 아무 일도 안 한다.
        asyncio.create_task(SqsConsumerService.robot_events_loop()),
        # 티칭 팬던트(조그/그리퍼) 세션 타임아웃(TP-11) 스윕. 조그 세션은 런타임
        # 상태라 서버 재시작 시 항상 비활성으로 시작하므로 복구 로직이 필요 없다.
        asyncio.create_task(TeachingPendantService.sweep_loop()),
    ]

    yield

    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)


app = FastAPI(title="소규모 3D 프린트 업장 관리 로봇 - 서버", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders.router)
app.include_router(state.router)
app.include_router(stats.router)
app.include_router(health.router)
app.include_router(work_requests.router)
app.include_router(board_stock.router)
app.include_router(receive_pos.router)
app.include_router(sqs.router)
app.include_router(teaching_pendant.router)

app.include_router(client_ws.router)
