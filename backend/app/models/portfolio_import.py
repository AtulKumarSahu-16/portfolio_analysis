from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PortfolioImport(Base):
    __tablename__ = "portfolio_imports"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "file_sha256", name="uq_portfolio_import_file_hash"),
        Index("ix_portfolio_import_portfolio_created", "portfolio_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_type: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="previewed")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    portfolio: Mapped["Portfolio"] = relationship()
    holding_snapshots: Mapped[list["ImportedHoldingSnapshot"]] = relationship(back_populates="import_batch", cascade="all, delete-orphan", passive_deletes=True)


class ImportedHoldingSnapshot(Base):
    __tablename__ = "imported_holding_snapshots"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id", "snapshot_date", "folio_reference", name="uq_imported_holding_portfolio_instrument_date_folio"),
        Index("ix_imported_holdings_portfolio_date", "portfolio_id", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False)
    import_id: Mapped[int] = mapped_column(ForeignKey("portfolio_imports.id", ondelete="CASCADE"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    folio_reference: Mapped[str] = mapped_column(String(64), nullable=False, default="no-folio", server_default="no-folio")
    folio_last4: Mapped[str | None] = mapped_column(String(4))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    nav: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    average_buy_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    invested_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    returns_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    xirr_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    portfolio: Mapped["Portfolio"] = relationship()
    instrument: Mapped["Instrument"] = relationship()
    import_batch: Mapped[PortfolioImport] = relationship(back_populates="holding_snapshots")
