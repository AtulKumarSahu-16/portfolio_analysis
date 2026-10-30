import httpx
import pytest
import io
import openpyxl

from conftest import mock_provider


async def _portfolio(client, email="import-owner@example.com"):
    response = await client.post("/api/auth/signup", json={"display_name": "Import Owner", "email": email, "password": "valid-password-123"})
    assert response.status_code == 201
    response = await client.post("/api/portfolios", json={"name": "Statements"})
    assert response.status_code == 201
    return response.json()["id"]


TRANSACTION_CSV = (
    "Scheme Name,Scheme Code,Transaction Date,Transaction Type,Units,NAV,Amount\n"
    "Example Equity Fund,100641,2026-02-10,Purchase,2,50,100\n"
).encode()


async def _preview(client, portfolio_id, content=TRANSACTION_CSV, filename="statement.csv", data=None):
    return await client.post(
        f"/api/portfolios/{portfolio_id}/imports/preview",
        files={"file": (filename, content, "text/csv")},
        data=data or {},
    )


@pytest.mark.asyncio
async def test_import_preview_confirm_history_and_exact_file_duplicate(api):
    client, _ = api
    portfolio_id = await _portfolio(client)
    preview = await _preview(client, portfolio_id)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["records"][0]["transaction_type"] == "BUY"
    assert "No investment records have been saved" in result["message"]

    duplicate_statement = await _preview(client, portfolio_id)
    assert duplicate_statement.status_code == 409

    confirm = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": result["import_id"],
        "records": [{
            "record_type": "transaction", "scheme_name": "Example Equity Fund", "scheme_code": 100641,
            "transaction_date": "2026-02-10", "transaction_type": "BUY", "units": "2", "nav": "50", "amount": "100",
        }],
    })
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["transaction_rows_imported"] == 1
    history = await client.get(f"/api/portfolios/{portfolio_id}/imports")
    assert history.status_code == 200
    assert history.json()[0]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_import_confirm_skips_existing_transaction_and_preview_can_cancel(api):
    client, _ = api
    portfolio_id = await _portfolio(client, "dedupe-import@example.com")
    first = (await _preview(client, portfolio_id)).json()
    first_confirm = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": first["import_id"],
        "records": [{
            "record_type": "transaction", "scheme_name": "Example Equity Fund", "scheme_code": 100641,
            "transaction_date": "2026-02-10", "transaction_type": "BUY", "units": "2", "nav": "50",
        }],
    })
    assert first_confirm.status_code == 200

    changed_csv = TRANSACTION_CSV.replace(b"Purchase,2,50,100", b"Purchase,2,50,100 ")
    second = await _preview(client, portfolio_id, changed_csv, "statement-copy.csv")
    assert second.status_code == 200
    duplicate_confirm = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": second.json()["import_id"],
        "records": [{
            "record_type": "transaction", "scheme_name": "Example Equity Fund", "scheme_code": 100641,
            "transaction_date": "2026-02-10", "transaction_type": "BUY", "units": "2", "nav": "50",
        }],
    })
    assert duplicate_confirm.status_code == 200
    assert duplicate_confirm.json()["skipped_duplicates"] == 1

    pending = await _preview(client, portfolio_id, TRANSACTION_CSV + b"\n", "pending.csv")
    assert pending.status_code == 200
    cancelled = await client.delete(f"/api/portfolios/{portfolio_id}/imports/{pending.json()['import_id']}")
    assert cancelled.status_code == 204


@pytest.mark.asyncio
async def test_holding_snapshot_import_updates_dashboard_without_ledger_duplication(api):
    client, app = api
    portfolio_id = await _portfolio(client, "snapshot-import@example.com")
    content = b"Scheme Name,Scheme Code,Units,NAV,Invested Amount,Current Value,As of Date\nExample Fund,100641,10,50,400,500,2026-03-31\n"
    preview = await _preview(client, portfolio_id, content, "holdings.csv")
    assert preview.status_code == 200, preview.text
    row = preview.json()["records"][0]
    assert row["record_type"] == "holding"
    confirmed = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": preview.json()["import_id"],
        "records": [{
            "record_type": "holding", "scheme_name": "Example Fund", "scheme_code": 100641,
            "snapshot_date": "2026-03-31", "units": "10", "nav": "50", "amount": "400", "current_value": "500",
        }],
    })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["holding_snapshots_imported"] == 1
    await mock_provider(app, lambda request: httpx.Response(200, json={"scheme_code": 100641, "latest_nav": 51, "latest_nav_date": "2026-10-29"}))
    holdings = await client.get(f"/api/portfolios/{portfolio_id}/holdings")
    assert holdings.status_code == 200, holdings.text
    assert holdings.json()["items"][0]["quantity"] == "10.0000000000"
    assert holdings.json()["items"][0]["cost_basis"] == "400.00"
    assert holdings.json()["items"][0]["current_value"] == "510.0000000000"


@pytest.mark.asyncio
async def test_groww_style_no_isin_holdings_import_separately_by_folio(api):
    client, _ = api
    portfolio_id = await _portfolio(client, "groww-no-isin@example.com")
    content = (
        b"HOLDINGS AS ON,2026-03-31\nScheme Name,AMC,Category,Sub-category,Folio No.,Units,Invested Value,Current Value,Returns,XIRR\n"
        b"Example Flexi Cap Fund,Example AMC,Equity,Flexi Cap,FOLIO-1234,10,1000,1200,200,12.5%\n"
        b"Example Flexi Cap Fund,Example AMC,Equity,Flexi Cap,FOLIO-5678,5,500,600,100,10.0%\n"
    )
    preview = await _preview(client, portfolio_id, content, "groww.csv")
    assert preview.status_code == 200, preview.text
    records = preview.json()["records"]
    assert all(row["record_type"] == "holding" and row["isin"] is None for row in records)
    imported = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": preview.json()["import_id"],
        "records": [{
            "record_type": "holding", "scheme_name": row["scheme_name"], "amc_name": row["amc_name"],
            "category": row["category"], "sub_category": row["sub_category"], "folio_number": row["folio_number"],
            "snapshot_date": row["snapshot_date"], "units": row["units"], "amount": row["amount"],
            "current_value": row["current_value"], "returns_value": row["returns_value"], "xirr_pct": row["xirr_pct"],
            "scheme_match_status": "unverified",
        } for row in records],
    })
    assert imported.status_code == 200, imported.text
    holdings = await client.get(f"/api/portfolios/{portfolio_id}/holdings")
    assert holdings.status_code == 200, holdings.text
    positions = holdings.json()["items"]
    assert len(positions) == 2
    assert {position["folio_last4"] for position in positions} == {"1234", "5678"}
    assert all(position["instrument"]["identity_status"] == "unverified" for position in positions)
    assert {position["current_value"] for position in positions} == {None}
    assert {position["data_status"] for position in positions} == {"unavailable"}


@pytest.mark.asyncio
async def test_stock_statement_preview_confirm_and_dashboard_valuation(api):
    client, app = api
    portfolio_id = await _portfolio(client, "stocks-import@example.com")
    def stock_provider(request):
        if request.url.path.endswith("/historical_data"):
            from app.services.market_data_service import india_today
            from datetime import timedelta
            previous = (india_today() - timedelta(days=1)).isoformat()
            return httpx.Response(200, json={"datasets": [{"metric": "Price", "label": "Price on NSE", "values": [[previous, "2500"], [india_today().isoformat(), "2700"]]}]})
        symbol = request.url.params.get("name", "RELIANCE").upper()
        return httpx.Response(200, json={
            "tickerId": symbol, "companyName": "Reliance Industries Limited" if symbol == "RELIANCE" else "Infosys Limited",
            "currentPrice": {"NSE": 2600 if symbol == "RELIANCE" else 1600, "BSE": 2599}, "ltp": 2600,
        })
    await mock_provider(app, stock_provider)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Stock Name", "Symbol", "Exchange", "Quantity", "Average Buy Price", "Invested Value", "Current Price", "Current Value", "Profit/Loss", "As Of Date"])
    sheet.append(["Reliance Industries Ltd", "RELIANCE", "NSE", 10, 2400, 24000, 2600, 26000, 2000, "2026-03-31"])
    sheet.append(["Infosys Ltd", "INFY", "NSE", 10, 1500, 15000, 1600, 16000, 1000, "2026-03-31"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    preview = await _preview(client, portfolio_id, buffer.getvalue(), "stocks.xlsx")
    assert preview.status_code == 200, preview.text
    records = preview.json()["records"]
    assert [row["asset_type"] for row in records] == ["stock", "stock"]
    assert [row["identity_status"] for row in records] == ["verified", "verified"]

    confirmed = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": preview.json()["import_id"],
        "records": [{
            "asset_type": row["asset_type"], "record_type": row["record_type"], "scheme_name": row["scheme_name"],
            "symbol": row["symbol"], "exchange": row["exchange"], "identity_status": row["identity_status"],
            "units": row["units"], "nav": row["nav"], "current_price": row["current_price"], "amount": row["amount"],
            "current_value": row["current_value"], "returns_value": row["returns_value"], "snapshot_date": row["snapshot_date"],
        } for row in records],
    })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["holding_snapshots_imported"] == 2
    holdings = await client.get(f"/api/portfolios/{portfolio_id}/holdings")
    assert holdings.status_code == 200, holdings.text
    assert {row["instrument"]["symbol"] for row in holdings.json()["items"]} == {"RELIANCE", "INFY"}
    assert {row["instrument"]["asset_type"] for row in holdings.json()["items"]} == {"stock"}
    assert {row["average_buy_price"] for row in holdings.json()["items"]} == {"2400.00000000", "1500.00000000"}
    assert all(row["current_price"] is not None for row in holdings.json()["items"])
    assert all(row["price_date"] for row in holdings.json()["items"])
    assert all(row["valuation_source"] == "previous_close" for row in holdings.json()["items"])


@pytest.mark.asyncio
async def test_stock_import_allows_missing_isin_and_indianapi_failure_as_unverified(api):
    client, app = api
    portfolio_id = await _portfolio(client, "stock-unverified@example.com")
    await mock_provider(app, lambda request: httpx.Response(401, json={"detail": "unauthorized"}))
    content = b"Company Name,Symbol,Exchange,Quantity,Average Cost,Cost Value,Market Value,Statement Date\nUnknown Co,UNKNOWN,NSE,2,10,20,22,2026-03-31\n"
    preview = await _preview(client, portfolio_id, content, "unknown-stock.csv")
    assert preview.status_code == 200, preview.text
    record = preview.json()["records"][0]
    assert record["isin"] is None
    assert record["identity_status"] == "unverified"
    assert "IndianAPI could not verify" in record["stock_match_message"]
    confirmed = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": preview.json()["import_id"],
        "records": [{
            "asset_type": "stock", "record_type": "holding", "scheme_name": record["scheme_name"],
            "symbol": record["symbol"], "exchange": record["exchange"], "identity_status": "unverified",
            "units": record["units"], "nav": record["nav"], "amount": record["amount"],
            "current_value": record["current_value"], "snapshot_date": record["snapshot_date"],
        }],
    })
    assert confirmed.status_code == 200, confirmed.text


@pytest.mark.asyncio
async def test_mixed_excel_import_confirms_stock_and_mutual_fund_together(api):
    client, app = api
    portfolio_id = await _portfolio(client, "mixed-import@example.com")
    await mock_provider(app, lambda request: httpx.Response(200, json={
        "tickerId": "RELIANCE", "companyName": "Reliance Industries Limited",
        "currentPrice": {"NSE": 110},
    }))
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Symbol", "Exchange", "AMC", "Folio Number", "Scheme Code", "ISIN", "Units", "Average Cost", "NAV", "Invested Value", "Current Price", "Current Value", "As Of Date"])
    sheet.append(["Reliance Industries Ltd", "RELIANCE", "NSE", None, None, None, None, 1, 100, None, 100, 110, 110, "2026-03-31"])
    sheet.append(["Example Index Fund", None, None, "Example AMC", "FOLIO-42", 100641, None, 10, None, 20, 180, None, 200, "2026-03-31"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    preview = await _preview(client, portfolio_id, buffer.getvalue(), "mixed.xlsx")
    assert preview.status_code == 200, preview.text
    rows = preview.json()["records"]
    assert [row["asset_type"] for row in rows] == ["stock", "mutual_fund"]
    confirmed = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": preview.json()["import_id"],
        "records": [{
            "asset_type": row["asset_type"], "record_type": "holding", "scheme_name": row["scheme_name"],
            "symbol": row["symbol"], "exchange": row["exchange"], "amc_name": row["amc_name"],
            "folio_number": row["folio_number"], "scheme_code": row["scheme_code"],
            "identity_status": row.get("identity_status", "unverified"), "scheme_match_status": "unverified",
            "units": row["units"], "nav": row["nav"], "current_price": row["current_price"],
            "amount": row["amount"], "current_value": row["current_value"], "snapshot_date": row["snapshot_date"],
        } for row in rows],
    })
    assert confirmed.status_code == 200, confirmed.text
    holdings = await client.get(f"/api/portfolios/{portfolio_id}/holdings")
    assert holdings.status_code == 200, holdings.text
    assert {row["instrument"]["asset_type"] for row in holdings.json()["items"]} == {"stock", "mutual_fund"}


@pytest.mark.asyncio
async def test_duplicate_stock_holding_rows_are_flagged_and_existing_snapshot_skipped(api):
    client, _ = api
    portfolio_id = await _portfolio(client, "duplicate-stock@example.com")
    content = b"Stock Name,Symbol,Exchange,Quantity,Average Buy Price,Invested Value,Current Value,As Of Date\nReliance,RELIANCE,NSE,1,100,100,110,2026-03-31\nReliance,RELIANCE,NSE,1,100,100,110,2026-03-31\n"
    first = await _preview(client, portfolio_id, content, "duplicate-stock.csv")
    assert first.status_code == 200, first.text
    assert first.json()["records"][1]["duplicate"] is True
    # Import one reviewed copy, then a content-distinct copy of the same holding.
    row = first.json()["records"][0]
    saved = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": first.json()["import_id"], "records": [{
            "asset_type": "stock", "record_type": "holding", "scheme_name": row["scheme_name"], "symbol": "RELIANCE",
            "exchange": "NSE", "identity_status": "unverified", "units": "1", "nav": "100", "amount": "100",
            "current_value": "110", "snapshot_date": "2026-03-31",
        }],
    })
    assert saved.status_code == 200, saved.text
    changed = content.replace(b"Reliance,RELIANCE", b"Reliance Industries,RELIANCE")
    second = await _preview(client, portfolio_id, changed, "duplicate-stock-copy.csv")
    assert second.status_code == 200, second.text
    row = second.json()["records"][0]
    skipped = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": second.json()["import_id"], "records": [{
            "asset_type": "stock", "record_type": "holding", "scheme_name": row["scheme_name"], "symbol": "RELIANCE",
            "exchange": "NSE", "identity_status": "unverified", "units": "1", "nav": "100", "amount": "100",
            "current_value": "110", "snapshot_date": "2026-03-31",
        }],
    })
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["skipped_duplicates"] == 1


@pytest.mark.asyncio
async def test_preview_auto_resolves_only_exact_scheme_and_amc_match(api):
    client, app = api
    portfolio_id = await _portfolio(client, "groww-match@example.com")
    def provider(request):
        if request.url.path.endswith("/api/funds/search"):
            return httpx.Response(200, json={"results": [
                {"scheme_code": 100641, "scheme_name": "Example Flexi Cap Fund", "fund_house": "Example AMC Mutual Fund", "isin": "INF123456789"},
            ]})
        return httpx.Response(200, json={"scheme_code": 100641, "scheme_name": "Example Flexi Cap Fund", "fund_house": "Example AMC Mutual Fund", "plan_type": "Regular", "option_type": "Growth", "isin": "INF123456789", "latest_nav": 23.45, "latest_nav_date": "2026-10-29"})
    await mock_provider(app, provider)
    content = b"HOLDINGS AS ON,2026-03-31\nScheme Name,AMC,Folio No.,Units,Invested Value,Current Value\nExample Flexi Cap Fund,Example AMC,1234,10,1000,1200\n"
    preview = await _preview(client, portfolio_id, content, "groww-exact.csv")
    assert preview.status_code == 200, preview.text
    record = preview.json()["records"][0]
    assert record["scheme_match_status"] == "exact"
    assert record["scheme_code"] == 100641
    assert record["isin"] == "INF123456789"
    assert record["identity_status"] == "verified"
    assert record["nav"] == "23.45"
    assert record["nav_date"] == "2026-10-29"


@pytest.mark.asyncio
async def test_preview_returns_dropdown_candidates_when_plan_is_ambiguous(api):
    client, app = api
    portfolio_id = await _portfolio(client, "groww-multiple-match@example.com")
    await mock_provider(app, lambda request: httpx.Response(200, json={"results": [
        {"scheme_code": 100641, "scheme_name": "Example Flexi Cap Fund - Regular Plan - Growth", "fund_house": "Example AMC Mutual Fund", "plan_type": "Regular", "option_type": "Growth", "isin": "INF123456789"},
        {"scheme_code": 100642, "scheme_name": "Example Flexi Cap Fund - Direct Plan - Growth", "fund_house": "Example AMC Mutual Fund", "plan_type": "Direct", "option_type": "Growth", "isin": "INF987654321"},
    ]}))
    content = b"HOLDINGS AS ON,2026-03-31\nScheme Name,AMC,Folio No.,Units,Invested Value,Current Value\nExample Flexi Cap Fund Growth,Example AMC,1234,10,1000,1200\n"
    preview = await _preview(client, portfolio_id, content, "groww-ambiguous.csv")
    assert preview.status_code == 200, preview.text
    record = preview.json()["records"][0]
    assert record["scheme_match_status"] == "multiple"
    assert record["scheme_code"] is None
    assert len(record["scheme_candidates"]) == 2


@pytest.mark.asyncio
async def test_import_invalid_file_and_invalid_confirm_are_rejected(api):
    client, _ = api
    portfolio_id = await _portfolio(client, "invalid-import@example.com")
    missing_columns = await _preview(client, portfolio_id, b"foo,bar\n1,2\n", "bad.csv")
    assert missing_columns.status_code == 422

    preview = await _preview(client, portfolio_id)
    assert preview.status_code == 200
    invalid = await client.post(f"/api/portfolios/{portfolio_id}/imports/confirm", json={
        "import_id": preview.json()["import_id"],
        "records": [{"record_type": "holding", "scheme_name": "Fund", "scheme_code": 100641, "units": "-1", "snapshot_date": "2026-03-31"}],
    })
    assert invalid.status_code == 422

    await client.post("/api/auth/logout", json={})
    assert (await client.get(f"/api/portfolios/{portfolio_id}/imports")).status_code == 401
