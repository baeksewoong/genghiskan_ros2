"""drop unused legacy columns from the virtual-robot era

- orders.pickup_delay_sec: 1~10초 자동 수령 시뮬레이션용 — 수령은 "수령하기" 버튼으로만 한다.
- robot_tasks.last_phase / error_code: 가상 로봇 task.feedback / task.result 기록용.
- printers.status 'UNLOADING': 가상 로봇 UNLOAD 디스패치용 — 현재는 DONE → EMPTY(success_unload1).

Revision ID: 0010_drop_unused_legacy_columns
Revises: 0009_drop_task_type_event_direction
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_drop_unused_legacy_columns"
down_revision: Union[str, None] = "0009_drop_task_type_event_direction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_PRINTER_STATUS = sa.Enum("EMPTY", "RESERVED", "PRINTING", "DONE", "UNLOADING", name="printer_status")
_NEW_PRINTER_STATUS = sa.Enum("EMPTY", "RESERVED", "PRINTING", "DONE", name="printer_status")


def upgrade() -> None:
    op.drop_column("orders", "pickup_delay_sec")
    op.drop_column("robot_tasks", "last_phase")
    op.drop_column("robot_tasks", "error_code")
    # 혹시 남아 있는 UNLOADING 행은 EMPTY로 돌린 뒤 ENUM에서 값을 뺀다.
    op.execute("UPDATE printers SET status = 'EMPTY', current_order_id = NULL WHERE status = 'UNLOADING'")
    op.alter_column(
        "printers", "status", existing_type=_OLD_PRINTER_STATUS, type_=_NEW_PRINTER_STATUS, existing_nullable=False
    )


def downgrade() -> None:
    op.alter_column(
        "printers", "status", existing_type=_NEW_PRINTER_STATUS, type_=_OLD_PRINTER_STATUS, existing_nullable=False
    )
    op.add_column("robot_tasks", sa.Column("error_code", sa.String(32), nullable=True))
    op.add_column("robot_tasks", sa.Column("last_phase", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("pickup_delay_sec", sa.SmallInteger, nullable=True))
