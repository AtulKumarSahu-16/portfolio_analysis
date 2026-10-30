from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db import get_session
from app.services import mutual_fund_service
from app.services import market_data_service
from app.utils.cache import get_cached, record_request, store_cached

router = APIRouter(prefix="/mutual-funds", tags=["mutual funds"])


def validate_dates(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(min_length=2, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(status_code=422, detail="q must contain at least two non-whitespace characters.")
    key = f"fund:search:{q.casefold()}:{page}:{page_size}"
    cached = await get_cached(session, key)
    if cached is not None:
        await record_request(session, "MFNAV", "fund_search", 200, True)
        return cached
    result = await mutual_fund_service.search_funds(request.app.state.http, settings, q, page, page_size)
    await store_cached(session, key, result, settings.cache_ttl_nav_seconds)
    await record_request(session, "MFNAV", "fund_search", 200, False)
    return result


@router.get("/{scheme_code}/nav")
async def latest_nav(
    scheme_code: int,
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    if scheme_code < 1:
        raise HTTPException(status_code=422, detail="scheme_code must be a positive integer.")
    key = f"fund:nav:{scheme_code}"
    cached = await get_cached(session, key)
    if cached is not None:
        await record_request(session, "MFNAV", "latest_nav", 200, True)
        return market_data_service.describe_nav(cached)
    result = await mutual_fund_service.latest_nav(request.app.state.http, settings, scheme_code)
    await store_cached(session, key, result, settings.cache_ttl_nav_seconds)
    await record_request(session, "MFNAV", "latest_nav", 200, False)
    return market_data_service.describe_nav(result)


@router.get("/{scheme_code}/history")
async def history(
    scheme_code: int,
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=250, ge=1, le=10000),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    if scheme_code < 1:
        raise HTTPException(status_code=422, detail="scheme_code must be a positive integer.")
    validate_dates(start_date, end_date)
    key = f"fund:history:{scheme_code}:{start_date}:{end_date}:{page}:{page_size}"
    cached = await get_cached(session, key)
    if cached is not None:
        await record_request(session, "MFNAV", "nav_history", 200, True)
        return cached
    result = await mutual_fund_service.nav_history(
        request.app.state.http,
        settings,
        scheme_code,
        start_date.isoformat() if start_date else None,
        end_date.isoformat() if end_date else None,
        page,
        page_size,
    )
    await store_cached(session, key, result, settings.cache_ttl_history_seconds)
    await record_request(session, "MFNAV", "nav_history", 200, False)
    return result
