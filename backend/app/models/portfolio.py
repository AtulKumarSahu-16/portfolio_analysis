from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (Index("ix_portfolios_owner_updated", "owner_id", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    owner: Mapped["User"] = relationship(back_populates="portfolios")
    transactions: Mapped[list["PortfolioTransaction"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan", passive_deletes=True)
    sip_schedules: Mapped[list["SIPSchedule"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan", passive_deletes=True)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        CheckConstraint("asset_type IN ('stock', 'mutual_fund')", name="ck_instruments_asset_type"),
        UniqueConstraint("provider", "provider_instrument_id", name="uq_instruments_provider_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40), index=True)
    exchange: Mapped[str | None] = mapped_column(String(12))
    scheme_code: Mapped[str | None] = mapped_column(String(32), index=True)
    isin: Mapped[str | None] = mapped_column(String(24), index=True)
    amc_name: Mapped[str | None] = mapped_column(String(180))
    category: Mapped[str | None] = mapped_column(String(120))
    sub_category: Mapped[str | None] = mapped_column(String(160))
    identity_status: Mapped[str] = mapped_column(String(20), nullable=False, default="verified", server_default="verified")
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_instrument_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transactions: Mapped[list["PortfolioTransaction"]] = relationship(back_populates="instrument")
    sip_schedules: Mapped[list["SIPSchedule"]] = relationship(back_populates="instrument")


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"
    __table_args__ = (
        CheckConstraint(
            "(side IN ('BUY', 'SELL') AND quantity IS NOT NULL AND quantity > 0 AND price_per_unit IS NOT NULL AND price_per_unit >= 0) "
            "OR (side IN ('DIVIDEND', 'FEE') AND cash_amount IS NOT NULL AND cash_amount >= 0)",
            name="ck_transactions_amount_fields",
        ),
        CheckConstraint("fees >= 0", name="ck_transactions_fees_nonnegative"),
        Index("ix_transactions_portfolio_trade_date", "portfolio_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(12), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    fees: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio_imports.id", ondelete="SET NULL"), nullable=True, index=True)
    folio_reference: Mapped[str | None] = mapped_column(String(64), index=True)
    folio_last4: Mapped[str | None] = mapped_column(String(4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")
    instrument: Mapped[Instrument] = relationship(back_populates="transactions")


class SIPSchedule(Base):
    __tablename__ = "sip_schedules"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_sip_amount_positive"),
        CheckConstraint("frequency IN ('WEEKLY', 'MONTHLY', 'QUARTERLY')", name="ck_sip_frequency"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_sip_date_order"),
        Index("ix_sip_portfolio_active", "portfolio_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    frequency: Mapped[str] = mapped_column(String(12), nullable=False, default="MONTHLY")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    portfolio: Mapped[Portfolio] = relationship(back_populates="sip_schedules")
    instrument: Mapped[Instrument] = relationship(back_populates="sip_schedules")


class FundAllocationSnapshot(Base):
    __tablename__ = "fund_allocation_snapshots"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id", "snapshot_date", name="uq_fund_allocation_portfolio_instrument_date"),
        CheckConstraint("large_cap_pct IS NULL OR (large_cap_pct >= 0 AND large_cap_pct <= 100)", name="ck_fund_alloc_large_range"),
        CheckConstraint("mid_cap_pct IS NULL OR (mid_cap_pct >= 0 AND mid_cap_pct <= 100)", name="ck_fund_alloc_mid_range"),
        CheckConstraint("small_cap_pct IS NULL OR (small_cap_pct >= 0 AND small_cap_pct <= 100)", name="ck_fund_alloc_small_range"),
        CheckConstraint("commodities_pct IS NULL OR (commodities_pct >= 0 AND commodities_pct <= 100)", name="ck_fund_alloc_commodities_range"),
        Index("ix_fund_alloc_portfolio_date", "portfolio_id", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_label: Mapped[str] = mapped_column(String(180), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    large_cap_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    mid_cap_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    small_cap_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    commodities_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    portfolio: Mapped[Portfolio] = relationship()
    instrument: Mapped[Instrument] = relationship()
