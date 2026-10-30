"""Add statement-import batches and current-position snapshots.

Revision ID: 0003_portfolio_statement_imports
Revises: 0002_fund_allocation_snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_portfolio_statement_imports"
down_revision = "0002_fund_allocation_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_imports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_type", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_rows", sa.Integer(), nullable=False),
        sa.Column("skipped_duplicates", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("portfolio_id", "file_sha256", name="uq_portfolio_import_file_hash"),
    )
    op.create_index("ix_portfolio_import_portfolio_created", "portfolio_imports", ["portfolio_id", "created_at"])
    op.add_column("portfolio_transactions", sa.Column("import_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_transactions_import_id", "portfolio_transactions", "portfolio_imports", ["import_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_portfolio_transactions_import_id", "portfolio_transactions", ["import_id"])
    op.create_table(
        "imported_holding_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("portfolio_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 10), nullable=False),
        sa.Column("nav", sa.Numeric(20, 8)),
        sa.Column("current_value", sa.Numeric(20, 2)),
        sa.Column("invested_amount", sa.Numeric(20, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("portfolio_id", "instrument_id", "snapshot_date", name="uq_imported_holding_portfolio_instrument_date"),
    )
    op.create_index("ix_imported_holdings_portfolio_date", "imported_holding_snapshots", ["portfolio_id", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("ix_imported_holdings_portfolio_date", table_name="imported_holding_snapshots")
    op.drop_table("imported_holding_snapshots")
    op.drop_index("ix_portfolio_transactions_import_id", table_name="portfolio_transactions")
    op.drop_constraint("fk_transactions_import_id", "portfolio_transactions", type_="foreignkey")
    op.drop_column("portfolio_transactions", "import_id")
    op.drop_index("ix_portfolio_import_portfolio_created", table_name="portfolio_imports")
    op.drop_table("portfolio_imports")
