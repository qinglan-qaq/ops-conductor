"""attribute inventory ledger rows to orders and shipments

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add order/shipment attribution to inventory ledger rows."""
    op.add_column(
        "inventory_ledger", sa.Column("order_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "inventory_ledger", sa.Column("shipment_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_inventory_ledger_order_id",
        "inventory_ledger",
        "sales_order",
        ["order_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_inventory_ledger_shipment_id",
        "inventory_ledger",
        "shipment",
        ["shipment_id"],
        ["id"],
    )


def downgrade() -> None:
    """Drop order/shipment attribution from inventory ledger rows."""
    op.drop_constraint(
        "fk_inventory_ledger_shipment_id", "inventory_ledger", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_inventory_ledger_order_id", "inventory_ledger", type_="foreignkey"
    )
    op.drop_column("inventory_ledger", "shipment_id")
    op.drop_column("inventory_ledger", "order_id")
