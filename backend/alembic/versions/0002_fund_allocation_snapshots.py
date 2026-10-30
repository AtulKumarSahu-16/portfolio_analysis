"""Store dated fund cap and commodity allocation disclosures.

Revision ID: 0002_fund_allocation_snapshots
Revises: 0001_portfolio_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_fund_allocation_snapshots"
down_revision = "0001_portfolio_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fund_allocation_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("source_label", sa.String(length=180), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("large_cap_pct", sa.Numeric(5, 2)),
        sa.Column("mid_cap_pct", sa.Numeric(5, 2)),
        sa.Column("small_cap_pct", sa.Numeric(5, 2)),
        sa.Column("commodities_pct", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("large_cap_pct IS NULL OR (large_cap_pct >= 0 AND large_cap_pct <= 100)", name="ck_fund_alloc_large_range"),
        sa.CheckConstraint("mid_cap_pct IS NULL OR (mid_cap_pct >= 0 AND mid_cap_pct <= 100)", name="ck_fund_alloc_mid_range"),
        sa.CheckConstraint("small_cap_pct IS NULL OR (small_cap_pct >= 0 AND small_cap_pct <= 100)", name="ck_fund_alloc_small_range"),
        sa.CheckConstraint("commodities_pct IS NULL OR (commodities_pct >= 0 AND commodities_pct <= 100)", name="ck_fund_alloc_commodities_range"),
        sa.UniqueConstraint("portfolio_id", "instrument_id", "snapshot_date", name="uq_fund_allocation_portfolio_instrument_date"),
    )
    op.create_index("ix_fund_alloc_portfolio_date", "fund_allocation_snapshots", ["portfolio_id", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("ix_fund_alloc_portfolio_date", table_name="fund_allocation_snapshots")
    op.drop_table("fund_allocation_snapshots")
