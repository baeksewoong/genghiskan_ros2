"""add receive_pos table (수령대 1/2 현황)

작업요청(SQS) 경로: 수령대 점유 상태를 orders에서 계산하지 않고 별도 테이블로 관리한다.
EMPTY → RESERVED(unload2 발행) → OCCUPIED(success_unload2) → EMPTY(수령하기).
행(1, 2)은 앱 기동 시 bootstrap.ensure_seed_data가 없으면 만든다.

Revision ID: 0007_receive_pos_table
Revises: 0006_order_receive_pos_id
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_receive_pos_table"
down_revision: Union[str, None] = "0006_order_receive_pos_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "receive_pos",
        sa.Column("pos_id", sa.SmallInteger, primary_key=True),
        sa.Column(
            "status",
            sa.Enum("EMPTY", "RESERVED", "OCCUPIED", name="receive_pos_status"),
            nullable=False,
            server_default="EMPTY",
        ),
        sa.Column("current_order_id", sa.BigInteger, sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("receive_pos")
