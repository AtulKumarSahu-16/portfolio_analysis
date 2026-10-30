"""Persist dated market observations and scheduled refresh runs.

Revision ID: 0006_daily_market_data_refresh
Revises: 0005_imported_stock_prices
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_daily_market_data_refresh"
down_revision = "0005_imported_stock_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instrument_market_data_snapshots",
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("market_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_timestamp", sa.String(length=80)),
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_market_data_snapshot_date", "instrument_market_data_snapshots", ["market_date"])
    op.create_table(
        "market_data_refresh_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("refresh_date", sa.Date(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("instruments_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("instruments_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
    )
    op.create_index("ix_market_data_refresh_date_status", "market_data_refresh_runs", ["refresh_date", "status"])


def downgrade() -> None:
    op.drop_index("ix_market_data_refresh_date_status", table_name="market_data_refresh_runs")
    op.drop_table("market_data_refresh_runs")
    op.drop_index("ix_market_data_snapshot_date", table_name="instrument_market_data_snapshots")
    op.drop_table("instrument_market_data_snapshots")
