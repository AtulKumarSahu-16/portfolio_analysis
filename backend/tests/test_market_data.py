import httpx
import pytest
from datetime import date
from fastapi import HTTPException

from conftest import mock_provider
from app.core.config import Settings
from app.services.market_data_service import describe_nav, previous_stock_close


@pytest.mark.asyncio
async def test_stock_quote_success_and_database_cache(api):
    client, app = api
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/stock"
        assert request.url.params["name"] == "INFY"
        assert request.headers["X-API-Key"] == "test-key"
        return httpx.Response(200, json={"INFY": {"ltp": 1420.5, "timestamp": "2026-10-29 15:30:00"}})

    await mock_provider(app, handler)
    first = await client.get("/api/stocks/INFY/price")
    second = await client.get("/api/stocks/INFY/price")
    assert first.status_code == 200
    assert first.json()["market_data"]["ltp"] == 1420.5
    assert second.json() == first.json()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_stock_history_maps_documented_price_points(api):
    client, app = api
    await mock_provider(app, lambda request: httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [["2026-10-28", "100.2"]]}]}))
    response = await client.get("/api/stocks/TCS/history?period=6m")
    assert response.status_code == 200
    assert response.json()["points"] == [{"date": "2026-10-28", "price": "100.2"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("as_of", "values", "expected_date", "expected_price"),
    [
        (date(2026, 10, 30), [["2026-10-29", "101.25"], ["2026-10-30", "102.00"]], "2026-10-29", "101.25"),
        (date(2026, 10, 26), [["2026-10-23", "99.50"], ["2026-10-26", "100.00"]], "2026-10-23", "99.50"),
        # Simulates two market holidays before the latest available close.
        (date(2026, 10, 29), [["2026-10-26", "98.75"], ["2026-10-29", "105.00"]], "2026-10-26", "98.75"),
    ],
)
async def test_previous_close_uses_latest_dated_observation_before_today(api, as_of, values, expected_date, expected_price):
    _, app = api
    await mock_provider(app, lambda request: httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": values}]}))
    result = await previous_stock_close(app.state.http, Settings(indianapi_api_key="test-key"), "INFY", as_of=as_of)
    assert result["price"] == expected_price
    assert result["price_date"] == expected_date
    assert result["source"] == "IndianAPI"
    assert result["data_status"] == "updated"
    assert result["queried_at"]


@pytest.mark.asyncio
async def test_previous_close_missing_dated_history_is_unavailable_not_live_fallback(api):
    _, app = api
    await mock_provider(app, lambda request: httpx.Response(200, json={"datasets": [{"metric": "Price", "values": [["2026-10-30", "105"]]}]}))
    with pytest.raises(HTTPException, match="dated previous closing"):
        await previous_stock_close(app.state.http, Settings(indianapi_api_key="test-key"), "UNKNOWN", as_of=date(2026, 10, 30))


@pytest.mark.asyncio
async def test_previous_close_endpoint_uses_historical_data_and_backend_api_key(api):
    client, app = api
    from app.services.market_data_service import india_today
    from datetime import timedelta
    previous = (india_today() - timedelta(days=1)).isoformat()
    def handler(request):
        assert request.url.path == "/historical_data"
        assert request.url.params["stock_name"] == "INFY"
        assert request.url.params["filter"] == "price"
        assert request.headers["X-API-Key"] == "test-key"
        return httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [[previous, "1500"], [india_today().isoformat(), "1550"]]}]})
    await mock_provider(app, handler)
    response = await client.get("/api/stocks/INFY/previous-close")
    assert response.status_code == 200, response.text
    assert response.json()["price"] == "1500"
    assert response.json()["price_date"] == previous
    assert response.json()["data_status"] == "updated"


def test_nav_publication_date_is_separate_from_query_time_and_old_nav_is_delayed():
    nav = describe_nav({"source": "MFNAV", "nav": "50.25", "nav_date": "2026-10-19"}, as_of=date(2026, 10, 30))
    assert nav["nav_date"] == "2026-10-19"
    assert nav["queried_at"]
    assert nav["data_status"] == "delayed"


def test_invalid_nav_response_is_unavailable():
    with pytest.raises(HTTPException, match="valid NAV"):
        describe_nav({"nav": None, "nav_date": None}, as_of=date(2026, 10, 30))


@pytest.mark.asyncio
async def test_fund_search_latest_and_history(api):
    client, app = api

    def handler(request):
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"scheme_code": 100641, "scheme_name": "Fund name"}], "total": 1, "page": 1, "page_size": 20})
        if request.url.path == "/api/funds/100641":
            return httpx.Response(200, json={"scheme_code": 100641, "scheme_name": "Fund name", "latest_nav": 50.25, "latest_nav_date": "2026-10-28"})
        return httpx.Response(200, json={"fund_details": {"scheme_code": 100641}, "data": [{"nav_date": "2026-10-28", "nav": 50.25}], "total": 1, "page": 1, "page_size": 250})

    await mock_provider(app, handler)
    assert (await client.get("/api/mutual-funds/search?q=fund")).json()["results"][0]["scheme_code"] == 100641
    assert (await client.get("/api/mutual-funds/100641/nav")).json()["nav"] == 50.25
    assert (await client.get("/api/mutual-funds/100641/history?start_date=2026-10-01&end_date=2026-10-29")).json()["data"][0]["nav"] == 50.25


@pytest.mark.asyncio
async def test_invalid_inputs_rejected_without_provider_request(api):
    client, app = api
    calls = []
    await mock_provider(app, lambda request: calls.append(request) or httpx.Response(200, json={}))
    assert (await client.get("/api/stocks/%3Cbad%3E/price")).status_code == 422
    assert (await client.get("/api/stocks/INFY/history?period=2yr")).status_code == 422
    assert (await client.get("/api/mutual-funds/search?q=x")).status_code == 422
    assert (await client.get("/api/mutual-funds/100641/history?start_date=2026-10-20&end_date=2026-10-01")).status_code == 422
    assert not calls


@pytest.mark.asyncio
async def test_upstream_timeout_and_rate_limit_are_safe(api):
    client, app = api

    def timeout(request):
        raise httpx.ReadTimeout("private upstream detail")

    await mock_provider(app, timeout)
    response = await client.get("/api/stocks/INFY/price")
    assert response.status_code == 504
    assert "private upstream detail" not in response.text

    await mock_provider(app, lambda request: httpx.Response(429, json={"detail": "quota"}))
    response = await client.get("/api/mutual-funds/search?q=axis")
    assert response.status_code == 429
    assert "quota" not in response.text


@pytest.mark.asyncio
async def test_malformed_and_upstream_failure_responses_are_mapped(api):
    client, app = api
    await mock_provider(app, lambda request: httpx.Response(200, content=b"not-json"))
    response = await client.get("/api/mutual-funds/search?q=hdfc")
    assert response.status_code == 502

    await mock_provider(app, lambda request: httpx.Response(503, json={"internal": "provider detail"}))
    response = await client.get("/api/mutual-funds/search?q=hdfc")
    assert response.status_code == 502
    assert "provider detail" not in response.text
