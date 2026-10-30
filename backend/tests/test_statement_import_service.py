import io

import fitz
import openpyxl
import pytest

from app.services.statement_import_service import (
    IncorrectPdfPassword,
    ImportParseError,
    PasswordRequired,
    parse_statement,
)


def test_csv_holding_normalizes_currency_and_dates():
    content = (
        "Scheme Name,Folio Number,ISIN,Units,Purchase NAV,Invested Amount,Current Value,As of Date\n"
        'Example Equity Fund,12345,INF123456789,10,"₹50.25","500.00","602.50","31/03/2026"\n'
    ).encode()
    file_type, records = parse_statement(content, "statement.csv")
    assert file_type == "csv"
    assert records[0]["record_type"] == "holding"
    assert records[0]["units"] == "10"
    assert records[0]["average_cost"] == "50.25"
    assert records[0]["current_price"] == "60.25"
    assert records[0]["field_sources"]["current_price"] == "calculated"
    assert records[0]["snapshot_date"] == "2026-03-31"
    assert records[0]["current_value"] == "602.50"


def test_csv_transaction_rows_are_distinguished_and_duplicates_flagged():
    content = (
        "Scheme Name,Scheme Code,Transaction Date,Transaction Type,Units,NAV,Amount\n"
        "Example Equity Fund,100641,2026-02-10,Purchase,2,50,100\n"
        "Example Equity Fund,100641,2026-02-10,Purchase,2,50,100\n"
    ).encode()
    _, records = parse_statement(content, "transactions.csv")
    assert records[0]["record_type"] == "transaction"
    assert records[0]["transaction_type"] == "BUY"
    assert records[1]["duplicate"] is True


def test_missing_headers_and_unsupported_file_are_rejected():
    with pytest.raises(ImportParseError, match="Could not identify"):
        parse_statement(b"foo,bar\n1,2\n", "statement.csv")
    with pytest.raises(ImportParseError, match="Unsupported file type"):
        parse_statement(b"data", "statement.txt")


def test_invalid_numbers_and_dates_are_flagged_for_review():
    content = (
        "Scheme Name,Scheme Code,Transaction Date,Transaction Type,Units,NAV,Amount\n"
        "Example Equity Fund,100641,not-a-date,Purchase,not-units,not-nav,not-amount\n"
    ).encode()
    _, records = parse_statement(content, "bad-values.csv")
    assert records[0]["extraction_status"] == "review_required"
    assert any("units" in warning for warning in records[0]["warnings"])
    assert any("date" in warning for warning in records[0]["warnings"])


def test_xlsx_statement_parses():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Fund Name", "AMFI Code", "Transaction Date", "Transaction Type", "Units", "NAV", "Amount"])
    sheet.append(["Example Equity Fund", 100641, "2026-02-10", "SIP Purchase", 2, 50, 100])
    buffer = io.BytesIO()
    workbook.save(buffer)
    _, records = parse_statement(buffer.getvalue(), "statement.xlsx")
    assert records[0]["transaction_type"] == "BUY"
    assert records[0]["transaction_date"] == "2026-02-10"


def test_xlsx_imports_each_recognized_worksheet_and_ignores_other_tabs():
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "Summary"
    first.append(["Portfolio Summary"])
    holdings = workbook.create_sheet("Stocks")
    holdings.append(["Company Name", "Symbol", "Quantity", "Average Cost", "Invested Value", "Current Value", "As Of Date"])
    holdings.append(["Infosys Ltd", "INFY", 2, 100, 200, 240, "2026-03-31"])
    funds = workbook.create_sheet("Funds")
    funds.append(["Scheme Name", "AMC", "Folio", "Units", "Invested Value", "Current Value", "As Of Date"])
    funds.append(["Example Fund", "Example AMC", "F-1", 3, 300, 330, "2026-03-31"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    _, records = parse_statement(buffer.getvalue(), "multi.xlsx")
    assert [(row["source_sheet"], row["asset_type"]) for row in records] == [("Stocks", "stock"), ("Funds", "mutual_fund")]


def test_common_values_are_decimal_derived_and_sources_reported():
    content = b"Company Name,Symbol,Quantity,Average Cost,Current Price,As Of Date\nInfosys Ltd,INFY,3,10.10,12.25,2026-03-31\n"
    _, records = parse_statement(content, "common.csv")
    row = records[0]
    assert row["average_cost"] == "10.10"
    assert row["amount"] == "30.30"
    assert row["current_value"] == "36.75"
    assert row["returns_value"] == "6.45"
    assert row["field_sources"] == {
        "units": "statement", "average_cost": "statement", "current_price": "statement",
        "invested_value": "calculated", "current_value": "calculated", "profit_loss": "calculated",
    }


def test_generic_name_quantity_rows_are_left_for_asset_type_review():
    _, records = parse_statement(b"Name,Quantity,As Of Date\nExample holding,2,2026-03-31\n", "ambiguous.csv")
    assert records[0]["asset_type"] == "ambiguous"


@pytest.mark.parametrize(
    ("content", "asset_type", "average_cost", "current_price", "current_value"),
    [
        (b"Company Name,Symbol,Quantity,Average Buy Price,As Of Date\nInfosys,INFY,10,250,2026-03-31\n", "stock", "250", None, None),
        (b"Company Name,Symbol,Quantity,Invested Value,As Of Date\nInfosys,INFY,10,2500,2026-03-31\n", "stock", "250", None, None),
        (b"Company Name,Symbol,Quantity,Current Value,As Of Date\nInfosys,INFY,10,2500,2026-03-31\n", "stock", None, "250", "2500"),
        (b"Scheme Name,Units,Invested Value,Statement Date\nExample Fund,100,10000,2026-03-31\n", "mutual_fund", "100", None, None),
        (b"Scheme Name,Units,Current Value,Statement Date\nExample Fund,100,12500,2026-03-31\n", "mutual_fund", None, "125", "12500"),
    ],
)
def test_common_calculation_cases(content, asset_type, average_cost, current_price, current_value):
    _, records = parse_statement(content, "common.csv")
    row = records[0]
    assert row["asset_type"] == asset_type
    assert row["average_cost"] == average_cost
    assert row["current_price"] == current_price
    assert row["current_value"] == current_value


def test_zero_quantity_is_not_changed_or_importable_without_review():
    _, records = parse_statement(b"Company Name,Symbol,Quantity,As Of Date\nInfosys,INFY,0,2026-03-31\n", "zero.csv")
    assert records[0]["units"] == "0"
    assert any("zero" in warning for warning in records[0]["warnings"])


def test_groww_holdings_as_on_parses_without_isin_and_preserves_folios():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["GROWW HOLDINGS STATEMENT"])
    sheet.append(["HOLDINGS AS ON", "31/03/2026"])
    sheet.append(["Scheme Name", "AMC", "Category", "Sub-category", "Folio No.", "Units", "Invested Value", "Current Value", "Returns", "XIRR"])
    sheet.append(["Example Flexi Cap Fund", "Example AMC Mutual Fund", "Equity", "Flexi Cap", "FOLIO-1234", 10.5, 1000, 1200, 200, "12.5%"])
    sheet.append(["Example Flexi Cap Fund", "Example AMC Mutual Fund", "Equity", "Flexi Cap", "FOLIO-5678", 5, 500, 600, 100, "10.0%"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    _, records = parse_statement(buffer.getvalue(), "groww.xlsx")
    assert len(records) == 2
    assert all(record["record_type"] == "holding" for record in records)
    assert all(record["isin"] is None and record["scheme_code"] is None for record in records)
    assert all(record["snapshot_date"] == "2026-03-31" for record in records)
    assert records[0]["category"] == "Equity"
    assert records[0]["sub_category"] == "Flexi Cap"
    assert records[0]["returns_value"] == "200"
    assert records[0]["xirr_pct"] == "12.5"
    assert records[0]["folio_number"] != records[1]["folio_number"]


def test_stock_excel_recognizes_reliance_and_infosys_without_isin():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Stock Name", "Symbol", "Exchange", "ISIN", "Quantity", "Average Buy Price", "Invested Value", "Current Price", "Current Value", "Profit/Loss", "As Of Date"])
    sheet.append(["Reliance Industries Ltd", "RELIANCE", "NSE", None, 10, 2400, 24000, 2600, 26000, 2000, "2026-03-31"])
    sheet.append(["Infosys Ltd", "INFY", "NSE", None, 10, 1500, 15000, 1600, 16000, 1000, "2026-03-31"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    _, records = parse_statement(buffer.getvalue(), "stocks.xlsx")
    assert [row["asset_type"] for row in records] == ["stock", "stock"]
    assert [row["symbol"] for row in records] == ["RELIANCE", "INFY"]
    assert all(row["record_type"] == "holding" and row["isin"] is None for row in records)
    assert records[0]["nav"] == "2400"
    assert records[0]["current_price"] == "2600"
    assert records[0]["current_value"] == "26000"


def test_mixed_stock_and_mutual_fund_xlsx_detects_each_row_type():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Symbol", "Exchange", "AMC", "Folio Number", "ISIN", "Units", "Average Cost", "NAV", "Invested Value", "Market Value", "As Of Date"])
    sheet.append(["Reliance Industries Ltd", "RELIANCE", "NSE", None, None, None, 10, 2400, None, 24000, 26000, "2026-03-31"])
    sheet.append(["Example Equity Fund", None, None, "Example AMC", "FOLIO-01", None, 25, None, 40, 900, 1000, "2026-03-31"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    _, records = parse_statement(buffer.getvalue(), "mixed.xlsx")
    assert [row["asset_type"] for row in records] == ["stock", "mutual_fund"]
    assert [row["record_type"] for row in records] == ["holding", "holding"]
    assert records[1]["isin"] is None
    assert records[0]["nav"] == "2400"
    assert records[1]["nav"] == "40"


def test_stock_csv_and_duplicate_rows_are_recognized():
    content = (
        "Company Name,Symbol,Market,Quantity,Average Cost,Cost Value,LTP,Market Value,P&L,Statement Date\n"
        "Infosys Ltd,INFY,NSE,10,1500,15000,1600,16000,1000,2026-03-31\n"
        "Infosys Ltd,INFY,NSE,10,1500,15000,1600,16000,1000,2026-03-31\n"
    ).encode()
    _, records = parse_statement(content, "stocks.csv")
    assert all(row["asset_type"] == "stock" for row in records)
    assert records[1]["duplicate"] is True


def test_mutual_fund_holdings_do_not_require_transaction_date_or_isin():
    content = b"Scheme Name,AMC,Folio No,Units,NAV,Invested Value,Current Value,Statement Date\nExample Fund,Example AMC,1234,2,50,90,100,2026-03-31\n"
    _, records = parse_statement(content, "funds.csv")
    assert records[0]["asset_type"] == "mutual_fund"
    assert records[0]["record_type"] == "holding"
    assert records[0]["isin"] is None


def test_unmatched_stock_header_gets_helpful_universal_column_error():
    with pytest.raises(ImportParseError, match="stock.*mutual funds"):
        parse_statement(b"Foo,Bar\n1,2\n", "unknown.csv")


def _pdf(encrypted=False):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), "Scheme Name | Scheme Code | Units | NAV | Current Value | As of Date")
    page.insert_text((40, 90), "Example Equity Fund | 100641 | 10 | 50.25 | 502.50 | 2026-03-31")
    buffer = io.BytesIO()
    kwargs = {"encryption": fitz.PDF_ENCRYPT_AES_256, "owner_pw": "owner-secret", "user_pw": "statement-secret"} if encrypted else {}
    doc.save(buffer, **kwargs)
    doc.close()
    return buffer.getvalue()


def test_text_pdf_extracts_without_ocr():
    _, records = parse_statement(_pdf(), "statement.pdf")
    assert records[0]["scheme_name"] == "Example Equity Fund"
    assert records[0]["units"] == "10"


def test_password_protected_pdf_requires_password_and_rejects_wrong_password():
    content = _pdf(encrypted=True)
    with pytest.raises(PasswordRequired):
        parse_statement(content, "protected.pdf")
    with pytest.raises(IncorrectPdfPassword):
        parse_statement(content, "protected.pdf", "wrong")
    _, records = parse_statement(content, "protected.pdf", "statement-secret")
    assert records[0]["scheme_code"] == 100641


def test_scanned_pdf_uses_ocr_fallback(monkeypatch):
    doc = fitz.open()
    doc.new_page()
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    monkeypatch.setattr("app.services.statement_import_service.shutil.which", lambda _: "/test/tesseract")
    monkeypatch.setattr("pytesseract.image_to_string", lambda image: "Scheme Name | Scheme Code | Units | As of Date\nExample Equity Fund | 100641 | 10 | 2026-03-31")
    _, records = parse_statement(buffer.getvalue(), "scan.pdf")
    assert records[0]["units"] == "10"


def test_scanned_pdf_explains_missing_tesseract(monkeypatch):
    doc = fitz.open()
    doc.new_page()
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    monkeypatch.setattr("app.services.statement_import_service.shutil.which", lambda _: None)
    with pytest.raises(ImportParseError, match="Install Tesseract"):
        parse_statement(buffer.getvalue(), "scan.pdf")
