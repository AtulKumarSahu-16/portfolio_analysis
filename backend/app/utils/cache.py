from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CachedResponse, MarketDataRequest


async def get_cached(session: AsyncSession, key: str) -> dict | None:
    row = await session.get(CachedResponse, key)
    if row is None:
        return None
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        await session.delete(row)
        await session.commit()
        return None
    return row.payload


async def store_cached(session: AsyncSession, key: str, payload: dict, ttl: int) -> None:
    if ttl <= 0:
        return
    await session.merge(CachedResponse(key=key, payload=payload, expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl)))
    await session.execute(delete(CachedResponse).where(CachedResponse.expires_at < datetime.now(timezone.utc)))
    await session.commit()


async def record_request(session: AsyncSession, provider: str, endpoint: str, status_code: int, cache_hit: bool) -> None:
    session.add(MarketDataRequest(provider=provider, endpoint=endpoint, status_code=status_code, cache_hit=cache_hit))
    await session.execute(delete(MarketDataRequest).where(MarketDataRequest.created_at < datetime.now(timezone.utc) - timedelta(days=30)))
    await session.commit()


async def prune_expired(session: AsyncSession) -> None:
    await session.execute(delete(CachedResponse).where(CachedResponse.expires_at < datetime.now(timezone.utc)))
    await session.commit()
