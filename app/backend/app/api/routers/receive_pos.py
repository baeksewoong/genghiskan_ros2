from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import ReceivePos
from app.repositories.receive_pos_repository import ReceivePosRepository
from app.schemas import ReceivePosOut

router = APIRouter(prefix="/api/receive-pos", tags=["receive-pos"])


@router.get("", response_model=list[ReceivePosOut])
async def list_receive_pos(session: AsyncSession = Depends(get_session)) -> list[ReceivePos]:
    """수령대(1, 2) 현황."""
    return await ReceivePosRepository.list_all(session)
