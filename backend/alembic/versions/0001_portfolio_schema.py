"""Add user accounts and portfolio transaction schema.

Revision ID: 0001_portfolio_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_portfolio_schema"
down_revision = None
branch_labels = None
depends_on = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_index_if_missing(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in indexes:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    existing = _existing_tables()
    if "cached_responses" not in existing:
        op.create_table(
            "cached_responses",
            sa.Column("key", sa.String(length=512), primary_key=True),
            sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "market_data_requests" not in existing:
        op.create_table(
            "market_data_requests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("endpoint", sa.String(length=100), nullable=False),
            sa.Column("cache_hit", sa.Boolean(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("display_name", sa.String(length=120), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "instruments" not in existing:
        op.create_table(
            "instruments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("asset_type", sa.String(length=20), nullable=False),
            sa.Column("display_name", sa.String(length=240), nullable=False),
            sa.Column("symbol", sa.String(length=40)),
            sa.Column("exchange", sa.String(length=12)),
            sa.Column("scheme_code", sa.String(length=32)),
            sa.Column("isin", sa.String(length=24)),
            sa.Column("provider", sa.String(length=40)),
            sa.Column("provider_instrument_id", sa.String(length=80)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("asset_type IN ('stock', 'mutual_fund')", name="ck_instruments_asset_type"),
            sa.UniqueConstraint("provider", "provider_instrument_id", name="uq_instruments_provider_id"),
        )
    if "portfolios" not in existing:
        op.create_table(
            "portfolios",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "portfolio_transactions" not in existing:
        op.create_table(
            "portfolio_transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
            sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("side", sa.String(length=12), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("quantity", sa.Numeric(24, 10)),
            sa.Column("price_per_unit", sa.Numeric(20, 8)),
            sa.Column("cash_amount", sa.Numeric(20, 2)),
            sa.Column("fees", sa.Numeric(20, 2), nullable=False),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint(
                "(side IN ('BUY', 'SELL') AND quantity IS NOT NULL AND quantity > 0 AND price_per_unit IS NOT NULL AND price_per_unit >= 0) "
                "OR (side IN ('DIVIDEND', 'FEE') AND cash_amount IS NOT NULL AND cash_amount >= 0)",
                name="ck_transactions_amount_fields",
            ),
            sa.CheckConstraint("fees >= 0", name="ck_transactions_fees_nonnegative"),
        )
    if "sip_schedules" not in existing:
        op.create_table(
            "sip_schedules",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
            sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("amount", sa.Numeric(20, 2), nullable=False),
            sa.Column("frequency", sa.String(length=12), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date()),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("amount > 0", name="ck_sip_amount_positive"),
            sa.CheckConstraint("frequency IN ('WEEKLY', 'MONTHLY', 'QUARTERLY')", name="ck_sip_frequency"),
            sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_sip_date_order"),
        )

    _create_index_if_missing("ix_cached_responses_expires_at", "cached_responses", ["expires_at"])
    _create_index_if_missing("ix_market_data_requests_provider", "market_data_requests", ["provider"])
    _create_index_if_missing("ix_users_email", "users", ["email"], unique=True)
    _create_index_if_missing("ix_instruments_symbol", "instruments", ["symbol"])
    _create_index_if_missing("ix_instruments_scheme_code", "instruments", ["scheme_code"])
    _create_index_if_missing("ix_instruments_isin", "instruments", ["isin"])
    _create_index_if_missing("ix_portfolios_owner_id", "portfolios", ["owner_id"])
    _create_index_if_missing("ix_portfolios_owner_updated", "portfolios", ["owner_id", "updated_at"])
    _create_index_if_missing("ix_portfolio_transactions_instrument_id", "portfolio_transactions", ["instrument_id"])
    _create_index_if_missing("ix_transactions_portfolio_trade_date", "portfolio_transactions", ["portfolio_id", "trade_date"])
    _create_index_if_missing("ix_sip_portfolio_active", "sip_schedules", ["portfolio_id", "is_active"])


def downgrade() -> None:
    # Downgrade removes portfolio records; take a backup before intentionally reverting.
    existing = _existing_tables()
    for table in ("sip_schedules", "portfolio_transactions", "portfolios", "instruments", "users"):
        if table in existing:
            op.drop_table(table)
