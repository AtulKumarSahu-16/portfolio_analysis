from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import HTTPException
import httpx

from app.core.config import Settings
from app.models import Instrument, InstrumentMarketDataSnapshot
from app.services import mutual_fund_service, stock_service
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

INDIA = ZoneInfo("Asia/Kolkata")


def india_today() -> date:
    return datetime.now(INDIA).date()


def data_status(observation_date: object, *, as_of: date | None = None) -> str:
    try:
        if isinstance(observation_date, datetime):
            measured = observation_date.date()
        else:
            measured = observation_date if isinstance(observation_date, date) else date.fromisoformat(str(observation_date)[:10])
    except (TypeError, ValueError):
        return "unavailable"
    age_days = ((as_of or india_today()) - measured).days
    if age_days < 0:
        return "unavailable"
    # The provider's dated observations determine the latest session. A seven day
    # grace period accommodates weekends and multi-day Indian market holidays.
    return "updated" if age_days <= 7 else "delayed"


async def previous_stock_close(
    client: httpx.AsyncClient,
    settings: Settings,
    symbol: str,
    *,
    exchange: str | None = None,
    as_of: date | None = None,
) -> dict:
    cutoff = as_of or india_today()
    history = await stock_service.get_history(client, settings, symbol, "1m", exchange=exchange)
    candidates = []
    for point in history.get("points", []):
        if not isinstance(point, dict):
            continue
        raw_date = point.get("date")
        try:
            market_date = date.fromisoformat(str(raw_date)[:10])
            price = Decimal(str(point.get("price")))
        except (TypeError, ValueError, InvalidOperation):
            continue
        if market_date < cutoff and price.is_finite() and price > 0:
            candidates.append((market_date, price, str(raw_date)))
    if not candidates:
        raise HTTPException(status_code=502, detail="IndianAPI did not return a dated previous closing price for this stock.")
    market_date, price, raw_timestamp = max(candidates, key=lambda item: item[0])
    timestamp = raw_timestamp if "T" in raw_timestamp or " " in raw_timestamp else None
    return {
        "symbol": symbol.upper(),
        "exchange": exchange.upper() if exchange else None,
        "price": str(price),
        "price_date": market_date.isoformat(),
        "price_timestamp": timestamp,
        "source": history.get("source", "IndianAPI"),
        "series_label": (history.get("series") or {}).get("label"),
        "data_status": data_status(market_date, as_of=cutoff),
        "queried_at": datetime.now(timezone.utc).isoformat(),
    }


def describe_nav(nav: dict, *, as_of: date | None = None) -> dict:
    try:
        value = Decimal(str(nav.get("nav")))
        nav_date = date.fromisoformat(str(nav.get("nav_date"))[:10])
        if not value.is_finite() or value <= 0:
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        raise HTTPException(status_code=502, detail="MFNAV did not return a valid NAV and publication date.") from None
    if nav_date >= (as_of or india_today()):
        raise HTTPException(status_code=502, detail="MFNAV has not returned a NAV from a completed previous valuation day.")
    return {
        **nav,
        "nav_date": nav_date.isoformat(),
        "data_status": data_status(nav_date, as_of=as_of),
        "queried_at": datetime.now(timezone.utc).isoformat(),
    }


async def fetch_instrument_observation(client: httpx.AsyncClient, settings: Settings, instrument: Instrument) -> dict:
    if instrument.asset_type == "stock":
        if not instrument.symbol:
            raise HTTPException(status_code=503, detail="The stock has no verified symbol.")
        result = await previous_stock_close(client, settings, instrument.symbol, exchange=instrument.exchange)
        return {
            "price": result["price"], "market_date": result["price_date"], "source": result["source"],
            "source_timestamp": result.get("price_timestamp"), "queried_at": result["queried_at"],
        }
    if not instrument.scheme_code:
        raise HTTPException(status_code=503, detail="The mutual fund has no verified scheme code.")
    try:
        scheme_code = int(instrument.scheme_code)
    except (TypeError, ValueError):
        raise HTTPException(status_code=503, detail="The mutual fund scheme code is invalid.") from None
    nav = describe_nav(await mutual_fund_service.latest_nav(client, settings, scheme_code))
    return {
        "price": str(nav["nav"]), "market_date": nav["nav_date"], "source": nav["source"],
        "source_timestamp": None, "queried_at": nav["queried_at"],
    }


async def refresh_instrument_snapshot(
    session: AsyncSession,
    client: httpx.AsyncClient,
    settings: Settings,
    instrument: Instrument,
) -> InstrumentMarketDataSnapshot:
    observation = await fetch_instrument_observation(client, settings, instrument)
    try:
        price = Decimal(str(observation["price"]))
        market_date = date.fromisoformat(observation["market_date"])
    except (TypeError, ValueError, InvalidOperation):
        raise HTTPException(status_code=502, detail="Market data did not include a valid price and observation date.") from None
    if not price.is_finite() or price <= 0:
        raise HTTPException(status_code=502, detail="Market data returned an invalid or zero value.")
    snapshot = await session.scalar(
        select(InstrumentMarketDataSnapshot)
        .where(InstrumentMarketDataSnapshot.instrument_id == instrument.id)
        .with_for_update()
    )
    if snapshot is not None and market_date < snapshot.market_date:
        raise HTTPException(status_code=502, detail="The provider returned older data; the previous valid observation was kept.")
    queried_at = datetime.fromisoformat(observation["queried_at"])
    if snapshot is None:
        snapshot = InstrumentMarketDataSnapshot(instrument_id=instrument.id)
        session.add(snapshot)
    snapshot.price = price
    snapshot.market_date = market_date
    snapshot.source = observation["source"]
    snapshot.source_timestamp = observation.get("source_timestamp")
    snapshot.queried_at = queried_at
    try:
        await session.flush()
    except IntegrityError:
        # A simultaneous first-time request may have inserted this shared instrument's
        # snapshot. Keep the committed observation instead of failing the dashboard.
        await session.rollback()
        snapshot = await session.get(InstrumentMarketDataSnapshot, instrument.id)
        if snapshot is not None and snapshot.market_date >= market_date and snapshot.price > 0:
            return snapshot
        raise
    return snapshot


def snapshot_payload(snapshot: InstrumentMarketDataSnapshot) -> dict:
    queried_at = snapshot.queried_at
    if queried_at.tzinfo is None:
        queried_at = queried_at.replace(tzinfo=timezone.utc)
    return {
        "price": str(snapshot.price),
        "price_date": snapshot.market_date.isoformat(),
        "price_timestamp": snapshot.source_timestamp,
        "source": snapshot.source,
        "queried_at": queried_at.isoformat(),
        "data_status": data_status(snapshot.market_date),
    }
