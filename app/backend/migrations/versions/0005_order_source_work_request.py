"""add orders.source=WORK_REQUEST (keep it out of the old DispatcherService's reach)

작업요청(SQS) 경로 주문을 MANUAL과 구분해, 가상 로봇(/ws/bridge) 경로의
DispatcherService._try_reserve_load가 board_stock 체크 없이 집어가지 못하게 한다.

Revision ID: 0005_order_source_work_request
Revises: 0004_defer_printer_assignment
Create Date: 2026-11-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_order_source_work_request"
down_revision: Union[str, None] = "0004_defer_printer_assignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_ORDER_SOURCE = sa.Enum("AUTO", "MANUAL", name="order_source")
_NEW_ORDER_SOURCE = sa.Enum("AUTO", "MANUAL", "WORK_REQUEST", name="order_source")


def upgrade() -> None:
    op.alter_column(
        "orders",
        "source",
        existing_type=_OLD_ORDER_SOURCE,
        type_=_NEW_ORDER_SOURCE,
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "orders",
        "source",
        existing_type=_NEW_ORDER_SOURCE,
        type_=_OLD_ORDER_SOURCE,
        existing_nullable=False,
    )
