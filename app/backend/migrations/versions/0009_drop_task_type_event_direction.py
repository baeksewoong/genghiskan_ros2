"""drop robot_tasks.type and event_logs.direction

가상 로봇 경로 제거 후 두 컬럼 모두 값이 하나만 남는다:
- robot_tasks.type: 작업 기록은 작업요청(SQS) 경로의 LOAD만 남는다 (unload는 기록하지 않음).
- event_logs.direction: 서버 → 웹(SERVER_TO_WEB)만 남는다 (/ws/bridge 제거).

Revision ID: 0009_drop_task_type_event_direction
Revises: 0008_drop_order_source
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_drop_task_type_event_direction"
down_revision: Union[str, None] = "0008_drop_order_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("robot_tasks", "type")
    op.drop_column("event_logs", "direction")


def downgrade() -> None:
    op.add_column(
        "event_logs",
        sa.Column(
            "direction",
            sa.Enum("SERVER_TO_WEB", "SERVER_TO_BRIDGE", "BRIDGE_TO_SERVER", name="event_direction"),
            nullable=False,
            server_default="SERVER_TO_WEB",
        ),
    )
    op.add_column(
        "robot_tasks",
        sa.Column("type", sa.Enum("LOAD", "UNLOAD", name="task_type"), nullable=False, server_default="LOAD"),
    )
