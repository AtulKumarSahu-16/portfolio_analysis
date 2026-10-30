from fastapi import HTTPException
import httpx

from app.core.config import Settings
from app.services.provider_http import get_json


def _stock_payload(payload: object, symbol: str) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="The stock provider returned an unexpected response shape.")
    for key in (symbol, symbol.upper()):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    # The current /stock endpoint can provide the detailed company response directly.
    if any(key in payload for key in ("ltp", "currentPrice", "tickerId", "companyName")):
        return payload
    raise HTTPException(status_code=502, detail="The provider response did not contain data for the requested symbol.")


async def get_price(client: httpx.AsyncClient, settings: Settings, symbol: str) -> dict:
    if not settings.indianapi_api_key:
        raise HTTPException(status_code=503, detail="IndianAPI is not configured. Set INDIANAPI_API_KEY on the backend.")
    payload = await get_json(
        client,
        f"{settings.indianapi_base_url.rstrip('/')}/stock",
        params={"name": symbol},
        headers={"X-API-Key": settings.indianapi_api_key},
    )
    market_data = _stock_payload(payload, symbol)
    return {"source": "IndianAPI", "symbol": symbol.upper(), "market_data": market_data}


async def get_history(client: httpx.AsyncClient, settings: Settings, symbol: str, period: str, exchange: str | None = None) -> dict:
    if not settings.indianapi_api_key:
        raise HTTPException(status_code=503, detail="IndianAPI is not configured. Set INDIANAPI_API_KEY on the backend.")
    payload = await get_json(
        client,
        f"{settings.indianapi_base_url.rstrip('/')}/historical_data",
        params={"stock_name": symbol, "period": period, "filter": "price"},
        headers={"X-API-Key": settings.indianapi_api_key},
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("datasets"), list):
        raise HTTPException(status_code=502, detail="The stock provider returned an unexpected history response shape.")
    price_series_list = [item for item in payload["datasets"] if isinstance(item, dict) and str(item.get("metric", "")).lower() == "price"]
    if exchange:
        matching = [item for item in price_series_list if exchange.upper() in str(item.get("label", "")).upper()]
        if matching:
            price_series_list = matching
        elif len(price_series_list) > 1 or any(any(market in str(item.get("label", "")).upper() for market in ("NSE", "BSE")) for item in price_series_list):
            raise HTTPException(status_code=502, detail="The provider history did not include the requested exchange.")
    price_series = price_series_list[0] if price_series_list else None
    if price_series is None:
        raise HTTPException(status_code=502, detail="The provider response did not include a price history series.")
    values = price_series.get("values")
    if not isinstance(values, list):
        raise HTTPException(status_code=502, detail="The provider returned an invalid price history series.")
    points = [{"date": pair[0], "price": pair[1]} for pair in values if isinstance(pair, list) and len(pair) >= 2]
    return {"source": "IndianAPI", "symbol": symbol.upper(), "period": period, "series": price_series, "points": points}
