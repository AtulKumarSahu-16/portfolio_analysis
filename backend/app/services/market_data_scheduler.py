import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db import SessionLocal, engine
from app.models import ImportedHoldingSnapshot, Instrument, InstrumentMarketDataSnapshot, MarketDataRefreshRun, PortfolioTransaction
from app.services import market_data_service

logger = logging.getLogger(__name__)
INDIA = ZoneInfo("Asia/Kolkata")
REFRESH_LOCK_ID = 8_731_225_001
_process_lock = asyncio.Lock()
_active_refresh_tasks: set[asyncio.Task] = set()


def create_market_data_scheduler(app: FastAPI) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=INDIA)
    scheduler.add_job(
        run_daily_refresh,
        CronTrigger(hour=0, minute=0, second=0, timezone=INDIA),
        id="portfolio-market-data-midnight-ist",
        args=[app],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        replace_existing=True,
    )
    scheduler.add_job(
        run_retry_refresh,
        CronTrigger(hour="0,6,12", minute=15, second=0, timezone=INDIA),
        id="portfolio-market-data-retries-ist",
        args=[app],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    return scheduler


async def run_daily_refresh(app: FastAPI) -> dict:
    return await run_market_data_refresh(app, trigger="daily")


async def run_retry_refresh(app: FastAPI) -> dict:
    return await run_market_data_refresh(app, trigger="retry", retry_only=True)


async def run_startup_catchup(app: FastAPI) -> dict:
    return await run_market_data_refresh(app, trigger="startup")


@asynccontextmanager
async def _refresh_lock(bind):
    if bind.dialect.name == "postgresql":
        async with bind.connect() as connection:
            acquired = bool((await connection.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": REFRESH_LOCK_ID})).scalar())
            await connection.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": REFRESH_LOCK_ID})
                    await connection.commit()
        return

    # SQLite is used by the test suite; production must use the shared PostgreSQL lock above.
    if _process_lock.locked():
        yield False
        return
    await _process_lock.acquire()
    try:
        yield True
    finally:
        _process_lock.release()


async def run_market_data_refresh(
    app: FastAPI,
    *,
    trigger: str,
    retry_only: bool = False,
    session_factory: async_sessionmaker | None = None,
    engine_override=None,
) -> dict:
    task = asyncio.current_task()
    if task is not None:
        _active_refresh_tasks.add(task)
    factory = session_factory or getattr(app.state, "session_factory", SessionLocal)
    bind = engine_override or factory.kw.get("bind") or engine
    started = datetime.now(INDIA)
    logger.info("Market-data refresh started trigger=%s started_at_ist=%s", trigger, started.isoformat())
    try:
        try:
            async with _refresh_lock(bind) as acquired:
                if not acquired:
                    logger.info("Market-data refresh skipped trigger=%s reason=another_instance_holds_lock", trigger)
                    return {"status": "skipped", "reason": "locked"}
                result = await _run_locked_refresh(app, factory, trigger, retry_only)
                return result
        except Exception:
            logger.exception("Market-data refresh failed trigger=%s started_at_ist=%s", trigger, started.isoformat())
            raise
    finally:
        if task is not None:
            _active_refresh_tasks.discard(task)


async def _run_locked_refresh(app: FastAPI, factory: async_sessionmaker, trigger: str, retry_only: bool) -> dict:
    now_ist = datetime.now(INDIA)
    refresh_date = now_ist.date()
    settings = getattr(app.state, "settings", get_settings())
    started_at = now_ist.astimezone(ZoneInfo("UTC"))
    async with factory() as session:
        if trigger in {"daily", "startup"}:
            completed_today = await session.scalar(
                select(MarketDataRefreshRun.id)
                .where(
                    MarketDataRefreshRun.refresh_date == refresh_date,
                    MarketDataRefreshRun.trigger.in_(("daily", "startup")),
                    MarketDataRefreshRun.status == "completed",
                )
                .limit(1)
            )
            if completed_today is not None:
                logger.info("Market-data refresh skipped trigger=%s reason=already_completed_today", trigger)
                return {"status": "skipped", "reason": "already_completed_today"}

        run = MarketDataRefreshRun(
            refresh_date=refresh_date,
            trigger=trigger,
            status="running",
            started_at=started_at,
            instruments_seen=0,
            instruments_updated=0,
            failures=[],
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

        held_instrument_ids = select(PortfolioTransaction.instrument_id).union(
            select(ImportedHoldingSnapshot.instrument_id)
        )
        instruments = list((await session.scalars(
            select(Instrument).where(Instrument.id.in_(held_instrument_ids)).order_by(Instrument.id)
        )).all())
        run.instruments_seen = len(instruments)
        failures = []
        updated = 0
        for instrument in instruments:
            await session.refresh(instrument)
            if retry_only:
                previous = await session.get(InstrumentMarketDataSnapshot, instrument.id)
                if previous is not None:
                    age = (refresh_date - previous.market_date).days
                    if age <= 3 and market_data_service.data_status(previous.market_date, as_of=refresh_date) != "delayed":
                        continue
            try:
                await market_data_service.refresh_instrument_snapshot(session, app.state.http, settings, instrument)
                await session.commit()
                updated += 1
            except HTTPException as exc:
                failure = {
                    "instrument_id": instrument.id,
                    "asset_type": instrument.asset_type,
                    "name": instrument.display_name,
                    "reason": str(exc.detail)[:240],
                }
                await session.rollback()
                failures.append(failure)
                logger.warning("Market-data refresh failed instrument_id=%s asset_type=%s reason=%s", failure["instrument_id"], failure["asset_type"], failure["reason"])

        async with factory() as finish_session:
            saved_run = await finish_session.get(MarketDataRefreshRun, run_id)
            finished_at = datetime.now(ZoneInfo("UTC"))
            if saved_run is not None:
                saved_run.status = "completed"
                saved_run.finished_at = finished_at
                saved_run.instruments_seen = len(instruments)
                saved_run.instruments_updated = updated
                saved_run.failures = failures
                await finish_session.commit()

    logger.info(
        "Market-data refresh completed trigger=%s finished_at_ist=%s instruments_seen=%d instruments_updated=%d failures=%d",
        trigger,
        finished_at.astimezone(INDIA).isoformat(),
        len(instruments),
        updated,
        len(failures),
    )
    return {"status": "completed", "instruments_seen": len(instruments), "instruments_updated": updated, "failures": failures}


async def wait_for_refresh_jobs() -> None:
    running = [task for task in _active_refresh_tasks if task is not asyncio.current_task()]
    if running:
        await asyncio.gather(*running, return_exceptions=True)
