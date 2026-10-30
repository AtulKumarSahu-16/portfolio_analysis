import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.models import (
    Base, Instrument, InstrumentMarketDataSnapshot, MarketDataRefreshRun,
    Portfolio, PortfolioTransaction, User,
)
from app.services.market_data_scheduler import (
    create_market_data_scheduler, run_market_data_refresh,
)
from app.services.market_data_service import india_today


def test_scheduler_uses_exact_midnight_with_explicit_ist_timezone():
    scheduler = create_market_data_scheduler(FastAPI())
    daily = scheduler.get_job("portfolio-market-data-midnight-ist")
    retries = scheduler.get_job("portfolio-market-data-retries-ist")
    assert daily.trigger.timezone.key == "Asia/Kolkata"
    previous = datetime(2026, 10, 29, 23, 59, tzinfo=ZoneInfo("Asia/Kolkata"))
    following = daily.trigger.get_next_fire_time(None, previous)
    assert (following.hour, following.minute, following.second) == (0, 0, 0)
    assert following.date() == date(2026, 10, 30)
    assert retries.trigger.timezone.key == "Asia/Kolkata"
    if scheduler.running:
        scheduler.shutdown(wait=False)


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _app(provider, settings):
    app = FastAPI()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    app.state.settings = settings
    return app


async def _seed_two_users(factory, *, old_market_date=None):
    async with factory() as session:
        users = [
            User(email=f"market-{number}@example.com", password_hash="hash", display_name=f"User {number}")
            for number in (1, 2)
        ]
        session.add_all(users)
        await session.flush()
        portfolios = [Portfolio(owner_id=user.id, name="Investments", currency="INR") for user in users]
        session.add_all(portfolios)
        await session.flush()
        stock = Instrument(asset_type="stock", display_name="Shared Stock", symbol="SHARED", exchange="NSE", provider="IndianAPI", provider_instrument_id="SHARED")
        fund = Instrument(asset_type="mutual_fund", display_name="Shared Fund", scheme_code="100641", provider="MFNAV", provider_instrument_id="100641")
        session.add_all([stock, fund])
        await session.flush()
        for portfolio in portfolios:
            session.add_all([
                PortfolioTransaction(portfolio_id=portfolio.id, instrument_id=stock.id, side="BUY", trade_date=date(2026, 1, 2), quantity=Decimal("2"), price_per_unit=Decimal("100"), fees=Decimal("0")),
                PortfolioTransaction(portfolio_id=portfolio.id, instrument_id=fund.id, side="BUY", trade_date=date(2026, 1, 2), quantity=Decimal("5"), price_per_unit=Decimal("20"), fees=Decimal("0")),
            ])
        if old_market_date:
            session.add(InstrumentMarketDataSnapshot(
                instrument_id=stock.id, price=Decimal("77"), market_date=old_market_date,
                source="IndianAPI", queried_at=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            ))
        await session.commit()
        return stock.id, fund.id


@pytest.mark.asyncio
async def test_refresh_deduplicates_shared_instruments_and_startup_catchup_skips_completed():
    engine, factory = await _database()
    today = india_today()
    observation_date = today - timedelta(days=1)
    calls = []

    def provider(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/historical_data"):
            return httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [[observation_date.isoformat(), "123.45"]]}]})
        if request.url.path == "/api/funds/100641":
            return httpx.Response(200, json={"scheme_code": 100641, "latest_nav": "25.50", "latest_nav_date": observation_date.isoformat()})
        return httpx.Response(404)

    app = _app(provider, Settings(indianapi_api_key="test-key"))
    try:
        await _seed_two_users(factory)
        result = await run_market_data_refresh(app, trigger="daily", session_factory=factory, engine_override=engine)
        assert result["instruments_seen"] == 2
        assert result["instruments_updated"] == 2
        assert len(calls) == 2
        async with factory() as session:
            snapshots = list((await session.scalars(select(InstrumentMarketDataSnapshot))).all())
            assert {row.market_date for row in snapshots} == {observation_date}
            assert {row.source for row in snapshots} == {"IndianAPI", "MFNAV / AMFI"}
            run_count = len((await session.scalars(select(MarketDataRefreshRun))).all())
        assert run_count == 1
        catchup = await run_market_data_refresh(app, trigger="startup", session_factory=factory, engine_override=engine)
        assert catchup == {"status": "skipped", "reason": "already_completed_today"}
        assert len(calls) == 2
    finally:
        await app.state.http.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_midnight_failure_keeps_last_valid_value_and_retry_updates_it():
    engine, factory = await _database()
    old_date = india_today() - timedelta(days=10)
    calls = 0

    def failed_provider(request):
        return httpx.Response(503, json={"detail": "provider temporarily unavailable"})

    app = _app(failed_provider, Settings(indianapi_api_key="test-key"))
    try:
        stock_id, _ = await _seed_two_users(factory, old_market_date=old_date)
        failed = await run_market_data_refresh(app, trigger="daily", session_factory=factory, engine_override=engine)
        assert failed["instruments_updated"] == 0
        assert failed["failures"]
        async with factory() as session:
            snapshot = await session.get(InstrumentMarketDataSnapshot, stock_id)
            assert snapshot.price == Decimal("77.00000000")
            assert snapshot.market_date == old_date

        new_date = india_today() - timedelta(days=1)
        def recovered_provider(request):
            nonlocal calls
            calls += 1
            if request.url.path.endswith("/historical_data"):
                return httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [[new_date.isoformat(), "130"]]}]})
            return httpx.Response(503)
        await app.state.http.aclose()
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(recovered_provider))
        retry = await run_market_data_refresh(app, trigger="retry", retry_only=True, session_factory=factory, engine_override=engine)
        assert retry["instruments_updated"] == 1
        async with factory() as session:
            snapshot = await session.get(InstrumentMarketDataSnapshot, stock_id)
            assert snapshot.price == Decimal("130.00000000")
            assert snapshot.market_date == new_date
    finally:
        await app.state.http.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_overlapping_scheduler_runs_are_skipped_by_process_lock():
    engine, factory = await _database()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    observation_date = india_today() - timedelta(days=1)

    async def provider(request):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        if request.url.path.endswith("/historical_data"):
            return httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [[observation_date.isoformat(), "123"]]}]})
        return httpx.Response(200, json={"scheme_code": 100641, "latest_nav": "25", "latest_nav_date": observation_date.isoformat()})

    app = _app(provider, Settings(indianapi_api_key="test-key"))
    try:
        await _seed_two_users(factory)
        first = asyncio.create_task(run_market_data_refresh(app, trigger="daily", session_factory=factory, engine_override=engine))
        await entered.wait()
        second = await run_market_data_refresh(app, trigger="retry", retry_only=True, session_factory=factory, engine_override=engine)
        assert second == {"status": "skipped", "reason": "locked"}
        release.set()
        result = await first
        assert result["instruments_updated"] == 2
        assert calls == 2
    finally:
        release.set()
        await app.state.http.aclose()
        await engine.dispose()
