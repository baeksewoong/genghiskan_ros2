"""defer printer assignment to success_load1 (robot_tasks.printer_slot nullable)

작업요청(SQS) 경로: 이제 dispatch 시점에는 프린터를 예약하지 않고, robot-events의
success_load1(베드 집기 성공) 수신 시점에 비로소 빈 프린터를 찾아 예약한다.
그 사이(DISPATCHING~success_load1 수신 전) robot_tasks 행은 printer_slot을 모른다.

Revision ID: 0004_defer_printer_assignment
Revises: 0003_remove_board_inventory
Create Date: 2026-11-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_defer_printer_assignment"
down_revision: Union[str, None] = "0003_remove_board_inventory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("robot_tasks", "printer_slot", existing_type=sa.SmallInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("robot_tasks", "printer_slot", existing_type=sa.SmallInteger(), nullable=False)
