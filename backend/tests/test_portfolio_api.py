from datetime import timedelta
from decimal import Decimal

import httpx
import pytest

from conftest import mock_provider


async def create_user_and_portfolio(client, email):
    signed_up = await client.post("/api/auth/signup", json={"display_name": "Portfolio Owner", "email": email, "password": "valid-password-123"})
    assert signed_up.status_code == 201, signed_up.json()
    portfolio = await client.post("/api/portfolios", json={"name": "Long term"})
    assert portfolio.status_code == 201, portfolio.json()
    return portfolio.json()["id"]


def stock_instrument():
    return {"asset_type": "stock", "display_name": "Example Corporation", "symbol": "EXAMPLE", "exchange": "NSE"}


def purchase(quantity="3", price="100", **overrides):
    return {
        "instrument": stock_instrument(),
        "side": "BUY",
        "trade_date": "2026-01-10",
        "quantity": quantity,
        "price_per_unit": price,
        "fees": "2",
        **overrides,
    }


@pytest.mark.asyncio
async def test_portfolio_transactions_holdings_and_safe_market_valuation(api):
    client, app = api
    await create_user_and_portfolio(client, "owner@example.com")
    portfolios = (await client.get("/api/portfolios")).json()
    portfolio_id = portfolios[0]["id"]
    created = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=purchase())
    assert created.status_code == 201, created.json()
    assert created.json()["instrument"]["symbol"] == "EXAMPLE"

    from app.services.market_data_service import india_today
    previous_day = (india_today() - timedelta(days=1)).isoformat()
    await mock_provider(app, lambda request: httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [[previous_day, "120"]]}]}))
    holdings = await client.get(f"/api/portfolios/{portfolio_id}/holdings")
    assert holdings.status_code == 200
    assert holdings.json()["items"][0]["quantity"] == "3.0000000000"
    assert Decimal(holdings.json()["total_cost_basis"]) == Decimal("302")
    assert Decimal(holdings.json()["current_value"]) == Decimal("360")
    assert holdings.json()["valuation_complete"] is True
    assert holdings.json()["items"][0]["price_date"] == previous_day
    assert Decimal(holdings.json()["items"][0]["profit_loss"]) == Decimal("58")
    assert Decimal(holdings.json()["items"][0]["return_pct"]).quantize(Decimal("0.01")) == Decimal("19.21")

    transactions = await client.get(f"/api/portfolios/{portfolio_id}/transactions")
    assert transactions.json()[0]["fees"] == "2.00"


@pytest.mark.asyncio
async def test_multiple_stocks_and_fund_use_dated_market_values(api):
    client, app = api
    portfolio_id = await create_user_and_portfolio(client, "mixed-valuations@example.com")
    stock_one = {**purchase(), "instrument": {"asset_type": "stock", "display_name": "Example One", "symbol": "ONE", "exchange": "NSE"}, "quantity": "2", "price_per_unit": "100", "fees": "0"}
    stock_two = {**purchase(), "instrument": {"asset_type": "stock", "display_name": "Example Two", "symbol": "TWO", "exchange": "NSE"}, "quantity": "1", "price_per_unit": "50", "fees": "0"}
    fund = {**purchase(), "instrument": {"asset_type": "mutual_fund", "display_name": "Example Fund", "scheme_code": 100641}, "quantity": "10", "price_per_unit": "20", "fees": "0"}
    for transaction in (stock_one, stock_two, fund):
        response = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=transaction)
        assert response.status_code == 201, response.text

    from app.services.market_data_service import india_today
    from datetime import timedelta
    close_date = (india_today() - timedelta(days=1)).isoformat()
    def provider(request):
        if request.url.path.endswith("/historical_data"):
            symbol = request.url.params["stock_name"]
            close = {"ONE": "120", "TWO": "45"}[symbol]
            return httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [[close_date, close]]}]})
        if request.url.path == "/api/funds/100641":
            return httpx.Response(200, json={"scheme_code": 100641, "latest_nav": "25", "latest_nav_date": close_date})
        return httpx.Response(404, json={"detail": "not found"})
    await mock_provider(app, provider)
    result = (await client.get(f"/api/portfolios/{portfolio_id}/holdings")).json()
    values = {row["instrument"]["symbol"] or row["instrument"]["scheme_code"]: Decimal(row["current_value"]) for row in result["items"]}
    assert values == {"ONE": Decimal("240.0000000000"), "TWO": Decimal("45.0000000000"), "100641": Decimal("250.0000000000")}
    assert Decimal(result["current_value"]) == Decimal("535.0000000000")
    assert Decimal(result["profit_loss"]) == Decimal("85.0000000000")
    assert result["valuation_complete"] is True


@pytest.mark.asyncio
async def test_zero_quantity_rejected_without_division(api):
    client, _ = api
    portfolio_id = await create_user_and_portfolio(client, "zero-quantity@example.com")
    rejected = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=purchase(quantity="0"))
    assert rejected.status_code == 422
    holdings = (await client.get(f"/api/portfolios/{portfolio_id}/holdings")).json()
    assert holdings["items"] == []


@pytest.mark.asyncio
async def test_unmatched_stock_and_provider_failure_are_unavailable_not_live(api):
    client, app = api
    portfolio_id = await create_user_and_portfolio(client, "unmatched-stock@example.com")
    response = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json={
        **purchase(), "instrument": {"asset_type": "stock", "display_name": "Unknown Listing", "symbol": "NOMATCH", "exchange": "NSE"},
    })
    assert response.status_code == 201
    await mock_provider(app, lambda request: httpx.Response(200, json={"datasets": []}) if request.url.path.endswith("/historical_data") else httpx.Response(200, json={"ltp": 9999}))
    item = (await client.get(f"/api/portfolios/{portfolio_id}/holdings")).json()["items"][0]
    assert item["current_price"] is None and item["current_value"] is None
    assert item["data_status"] == "unavailable"
    await mock_provider(app, lambda request: httpx.Response(503, json={"secret": "provider detail"}))
    result = await client.get(f"/api/portfolios/{portfolio_id}/holdings")
    assert result.status_code == 200
    assert result.json()["items"][0]["current_value"] is None
    assert result.json()["items"][0]["data_status"] == "unavailable"


@pytest.mark.asyncio
async def test_portfolio_ownership_and_short_sales_are_rejected(api):
    client, _ = api
    portfolio_id = await create_user_and_portfolio(client, "first@example.com")
    created = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=purchase(quantity="2"))
    assert created.status_code == 201

    too_many = await client.post(
        f"/api/portfolios/{portfolio_id}/transactions",
        json=purchase(quantity="3", price="110", side="SELL"),
    )
    assert too_many.status_code == 422

    await client.post("/api/auth/logout", json={})
    await create_user_and_portfolio(client, "second@example.com")
    hidden = await client.get(f"/api/portfolios/{portfolio_id}/transactions")
    assert hidden.status_code == 404
    denied = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=purchase())
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_transaction_edit_delete_and_future_dates(api):
    client, _ = api
    portfolio_id = await create_user_and_portfolio(client, "edit@example.com")
    created = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=purchase())
    transaction_id = created.json()["id"]
    edited = await client.put(f"/api/portfolios/{portfolio_id}/transactions/{transaction_id}", json={
        "side": "BUY", "trade_date": "2026-02-01", "quantity": "4", "price_per_unit": "95", "fees": "1", "notes": "Updated statement entry"
    })
    assert edited.status_code == 200
    assert Decimal(edited.json()["quantity"]) == Decimal("4")

    future = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=purchase(trade_date="2999-01-01"))
    assert future.status_code == 422
    deleted = await client.delete(f"/api/portfolios/{portfolio_id}/transactions/{transaction_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/portfolios/{portfolio_id}/transactions")).json() == []


@pytest.mark.asyncio
async def test_fund_purchase_can_store_sip_plan_without_creating_future_transactions(api):
    client, _ = api
    portfolio_id = await create_user_and_portfolio(client, "sip@example.com")
    body = {
        "instrument": {"asset_type": "mutual_fund", "display_name": "Fund from provider search", "scheme_code": 100641, "isin": "INF200K01LJ4"},
        "side": "BUY", "trade_date": "2026-01-10", "quantity": "10", "price_per_unit": "50", "fees": "0",
        "sip_schedule": {"amount": "5000", "frequency": "MONTHLY", "start_date": "2026-02-01"},
    }
    response = await client.post(f"/api/portfolios/{portfolio_id}/transactions", json=body)
    assert response.status_code == 201, response.json()
    schedules = await client.get(f"/api/portfolios/{portfolio_id}/sip-schedules")
    assert schedules.status_code == 200
    assert schedules.json()[0]["amount"] == "5000.00"
    transactions = await client.get(f"/api/portfolios/{portfolio_id}/transactions")
    assert len(transactions.json()) == 1
