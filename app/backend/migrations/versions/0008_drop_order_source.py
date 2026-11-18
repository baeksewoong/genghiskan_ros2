"""drop orders.source

가상 로봇 경로(AUTO/MANUAL 주문) 제거 후 모든 주문이 작업요청(WORK_REQUEST)으로만
만들어지므로 주문 출처 구분 컬럼이 더 이상 의미가 없다.

Revision ID: 0008_drop_order_source
Revises: 0007_receive_pos_table
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_drop_order_source"
down_revision: Union[str, None] = "0007_receive_pos_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ORDER_SOURCE = sa.Enum("AUTO", "MANUAL", "WORK_REQUEST", name="order_source")


def upgrade() -> None:
    op.drop_column("orders", "source")


def downgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("source", _ORDER_SOURCE, nullable=False, server_default="WORK_REQUEST"),
    )
