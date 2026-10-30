from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db import get_session
from app.utils.cache import get_cached, record_request, store_cached
from app.services import stock_service
from app.services import market_data_service

router = APIRouter(prefix="/stocks", tags=["stocks"])
Period = Literal["1m", "6m", "1yr", "3yr", "5yr", "10yr", "max"]


def validate_symbol(symbol: str) -> str:
    value = symbol.strip()
    if not value or len(value) > 80 or not all(ch.isalnum() or ch in " .&-" for ch in value):
        raise HTTPException(status_code=422, detail="Symbol must be a valid stock name or ticker.")
    return value


@router.get("/{symbol}/price")
async def stock_price(
    symbol: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    symbol = validate_symbol(symbol)
    key = f"stock:price:{symbol.upper()}"
    cached = await get_cached(session, key)
    if cached is not None:
        await record_request(session, "IndianAPI", "stock_price", 200, True)
        return cached
    result = await stock_service.get_price(request.app.state.http, settings, symbol)
    await store_cached(session, key, result, settings.cache_ttl_stock_seconds)
    await record_request(session, "IndianAPI", "stock_price", 200, False)
    return result


@router.get("/{symbol}/previous-close")
async def previous_close(
    symbol: str,
    request: Request,
    exchange: str | None = Query(default=None, pattern="^(NSE|BSE)$"),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    symbol = validate_symbol(symbol)
    market_day = market_data_service.india_today()
    key = f"stock:previous-close:{symbol.upper()}:{exchange or 'ANY'}:{market_day.isoformat()}"
    cached = await get_cached(session, key)
    if cached is not None:
        await record_request(session, "IndianAPI", "stock_previous_close", 200, True)
        return cached
    result = await market_data_service.previous_stock_close(request.app.state.http, settings, symbol, exchange=exchange)
    await store_cached(session, key, result, settings.cache_ttl_history_seconds)
    await record_request(session, "IndianAPI", "stock_previous_close", 200, False)
    return result


@router.get("/{symbol}/history")
async def stock_history(
    symbol: str,
    request: Request,
    period: Period = Query(default="1yr"),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    symbol = validate_symbol(symbol)
    key = f"stock:history:{symbol.upper()}:{period}"
    cached = await get_cached(session, key)
    if cached is not None:
        await record_request(session, "IndianAPI", "stock_history", 200, True)
        return cached
    result = await stock_service.get_history(request.app.state.http, settings, symbol, period)
    await store_cached(session, key, result, settings.cache_ttl_history_seconds)
    await record_request(session, "IndianAPI", "stock_history", 200, False)
    return result
