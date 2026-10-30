"""Support Groww holdings without ISIN and retain folio positions.

Revision ID: 0004_groww_folios
Revises: 0003_portfolio_statement_imports
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_groww_folios"
down_revision = "0003_portfolio_statement_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("instruments", sa.Column("amc_name", sa.String(180)))
    op.add_column("instruments", sa.Column("category", sa.String(120)))
    op.add_column("instruments", sa.Column("sub_category", sa.String(160)))
    op.add_column("instruments", sa.Column("identity_status", sa.String(20), server_default="verified", nullable=False))
    op.add_column("portfolio_transactions", sa.Column("folio_reference", sa.String(64)))
    op.create_index("ix_portfolio_transactions_folio_reference", "portfolio_transactions", ["folio_reference"])
    op.add_column("imported_holding_snapshots", sa.Column("folio_reference", sa.String(64), server_default="no-folio", nullable=False))
    op.add_column("imported_holding_snapshots", sa.Column("folio_last4", sa.String(4)))
    op.add_column("imported_holding_snapshots", sa.Column("returns_value", sa.Numeric(20, 2)))
    op.add_column("imported_holding_snapshots", sa.Column("xirr_pct", sa.Numeric(9, 4)))
    op.drop_constraint("uq_imported_holding_portfolio_instrument_date", "imported_holding_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_imported_holding_portfolio_instrument_date_folio",
        "imported_holding_snapshots",
        ["portfolio_id", "instrument_id", "snapshot_date", "folio_reference"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_imported_holding_portfolio_instrument_date_folio", "imported_holding_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_imported_holding_portfolio_instrument_date",
        "imported_holding_snapshots",
        ["portfolio_id", "instrument_id", "snapshot_date"],
    )
    op.drop_column("imported_holding_snapshots", "xirr_pct")
    op.drop_column("imported_holding_snapshots", "returns_value")
    op.drop_column("imported_holding_snapshots", "folio_last4")
    op.drop_column("imported_holding_snapshots", "folio_reference")
    op.drop_index("ix_portfolio_transactions_folio_reference", table_name="portfolio_transactions")
    op.drop_column("portfolio_transactions", "folio_reference")
    op.drop_column("instruments", "identity_status")
    op.drop_column("instruments", "sub_category")
    op.drop_column("instruments", "category")
    op.drop_column("instruments", "amc_name")
