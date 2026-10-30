import httpx
from fastapi import HTTPException


async def get_json(client: httpx.AsyncClient, url: str, *, params: dict | None = None, headers: dict | None = None):
    try:
        response = await client.get(url, params=params, headers=headers)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Market data was not found by the provider.")
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="The provider rate limit or request allowance was reached.")
        if response.status_code in (401, 403):
            raise HTTPException(status_code=503, detail="The provider rejected access. Check server-side API key and plan configuration.")
        if response.status_code >= 500:
            raise HTTPException(status_code=502, detail="The market data provider is temporarily unavailable.")
        if response.is_error:
            raise HTTPException(status_code=502, detail="The market data provider rejected the request.")
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="The provider returned invalid JSON.") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="The market data provider timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Could not connect to the market data provider.") from exc
