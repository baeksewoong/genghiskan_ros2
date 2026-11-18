from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import HealthOut


class HealthService:
    @staticmethod
    async def check(session: AsyncSession) -> HealthOut:
        db_ok = True
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            db_ok = False

        return HealthOut(db=db_ok)
