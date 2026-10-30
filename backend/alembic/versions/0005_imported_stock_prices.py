"""Preserve average buy and current prices from imported holdings.

Revision ID: 0005_imported_stock_prices
Revises: 0004_groww_folios
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_imported_stock_prices"
down_revision = "0004_groww_folios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("imported_holding_snapshots", sa.Column("average_buy_price", sa.Numeric(20, 8)))
    op.add_column("imported_holding_snapshots", sa.Column("current_price", sa.Numeric(20, 8)))


def downgrade() -> None:
    op.drop_column("imported_holding_snapshots", "current_price")
    op.drop_column("imported_holding_snapshots", "average_buy_price")
