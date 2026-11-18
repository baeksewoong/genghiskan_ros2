"""add orders.receive_pos_id (수령대 위치 1/2)

작업요청(SQS) 경로: success_unload1 수신 시 비어있는 수령대(1 → 2 순)를 골라 주문에
기록하고 unload2 명령의 receive_pos_id로 보낸다. UNLOADING/READY_FOR_PICKUP 상태이면서
receive_pos_id가 있는 주문이 해당 수령대를 점유한 것으로 본다.

Revision ID: 0006_order_receive_pos_id
Revises: 0005_order_source_work_request
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_order_receive_pos_id"
down_revision: Union[str, None] = "0005_order_source_work_request"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("receive_pos_id", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "receive_pos_id")
