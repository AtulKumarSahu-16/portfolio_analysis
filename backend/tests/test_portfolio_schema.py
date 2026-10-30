from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, Instrument, Portfolio, PortfolioTransaction, User


@pytest.mark.asyncio
async def test_portfolio_transaction_schema_enforces_positive_quantity():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as session:
        user = User(email="owner@example.test", password_hash="test-only-hash", display_name="Owner")
        portfolio = Portfolio(name="Long term", owner=user)
        instrument = Instrument(asset_type="stock", display_name="Example Corp", symbol="EXAMPLE")
        session.add_all([user, portfolio, instrument])
        await session.flush()
        invalid_transaction = PortfolioTransaction(
            portfolio_id=portfolio.id,
            instrument_id=instrument.id,
            side="BUY",
            trade_date=date(2026, 1, 1),
            quantity=0,
            price_per_unit=100,
        )
        session.add(invalid_transaction)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    await engine.dispose()
