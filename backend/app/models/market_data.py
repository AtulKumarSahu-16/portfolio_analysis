from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CachedResponse(Base):
    __tablename__ = "cached_responses"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class MarketDataRequest(Base):
    __tablename__ = "market_data_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InstrumentMarketDataSnapshot(Base):
    """Latest successfully observed close/NAV shared by all portfolio owners."""

    __tablename__ = "instrument_market_data_snapshots"
    __table_args__ = (Index("ix_market_data_snapshot_date", "market_date"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_timestamp: Mapped[str | None] = mapped_column(String(80))
    queried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MarketDataRefreshRun(Base):
    __tablename__ = "market_data_refresh_runs"
    __table_args__ = (Index("ix_market_data_refresh_date_status", "refresh_date", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refresh_date: Mapped[date] = mapped_column(Date, nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instruments_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    instruments_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failures: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
