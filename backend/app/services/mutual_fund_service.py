from fastapi import HTTPException
import httpx

from app.core.config import Settings
from app.services.provider_http import get_json


async def search_funds(client: httpx.AsyncClient, settings: Settings, q: str, page: int, page_size: int) -> dict:
    result = await get_json(client, f"{settings.mfnav_base_url.rstrip('/')}/api/funds/search", params={"q": q, "page": page, "page_size": page_size})
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise HTTPException(status_code=502, detail="MFNAV returned an unexpected search response shape.")
    return {"source": "MFNAV / AMFI", **result}


async def fund_details(client: httpx.AsyncClient, settings: Settings, scheme_code: int) -> dict:
    result = await get_json(client, f"{settings.mfnav_base_url.rstrip('/')}/api/funds/{scheme_code}")
    if not isinstance(result, dict) or "scheme_code" not in result:
        raise HTTPException(status_code=502, detail="MFNAV returned an unexpected fund response shape.")
    return {"source": "MFNAV / AMFI", **result}


async def fund_details_by_isin(client: httpx.AsyncClient, settings: Settings, isin: str) -> dict:
    result = await get_json(client, f"{settings.mfnav_base_url.rstrip('/')}/api/funds/{isin}")
    if not isinstance(result, dict) or "scheme_code" not in result:
        raise HTTPException(status_code=502, detail="MFNAV did not resolve this ISIN to a scheme code.")
    return {"source": "MFNAV / AMFI", **result}


async def latest_nav(client: httpx.AsyncClient, settings: Settings, scheme_code: int) -> dict:
    details = await fund_details(client, settings, scheme_code)
    if "latest_nav" not in details or "latest_nav_date" not in details:
        raise HTTPException(status_code=502, detail="MFNAV did not provide a latest NAV and its date for this scheme.")
    return {"source": details["source"], "scheme_code": details["scheme_code"], "scheme_name": details.get("scheme_name"), "nav": details["latest_nav"], "nav_date": details["latest_nav_date"]}


async def nav_history(client: httpx.AsyncClient, settings: Settings, scheme_code: int, start_date: str | None, end_date: str | None, page: int, page_size: int) -> dict:
    params = {"page": page, "page_size": page_size}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    result = await get_json(client, f"{settings.mfnav_base_url.rstrip('/')}/api/nav/{scheme_code}", params=params)
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise HTTPException(status_code=502, detail="MFNAV returned an unexpected NAV history response shape.")
    return {"source": "MFNAV / AMFI", **result}
