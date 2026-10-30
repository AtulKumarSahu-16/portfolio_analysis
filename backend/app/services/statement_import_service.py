import csv
import hashlib
import io
import itertools
import re
import shutil
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import fitz
import openpyxl
import xlrd
from PIL import Image


class ImportParseError(ValueError):
    pass


class PasswordRequired(ImportParseError):
    pass


class IncorrectPdfPassword(ImportParseError):
    pass


MAX_IMPORT_BYTES = 15 * 1024 * 1024
SUPPORTED = {".pdf", ".csv", ".xlsx", ".xls"}

HEADER_ALIASES = {
    "scheme_name": {"scheme", "scheme name", "fund name", "mutual fund", "mutual fund name", "scheme description", "investment name", "stock name", "company name", "security name", "company", "stock", "scrip name", "name"},
    "amc_name": {"amc", "amc name", "amc fund house", "amc fund house name", "amc/fund house", "fund house", "mutual fund house", "mutual fund company", "asset management company", "asset management company name", "name of asset management company"},
    "category": {"category", "scheme category", "fund category"},
    "sub_category": {"sub category", "sub-category", "subcategory", "scheme sub category", "scheme sub-category"},
    "folio_number": {"folio", "folio no", "folio number", "folio no."},
    "isin": {"isin", "isin code", "security isin"},
    "scheme_code": {"scheme code", "scheme id", "amfi code", "fund code"},
    "units": {"units", "unit", "balance units", "units held", "closing units", "allotted units", "no of units", "quantity", "qty", "shares", "share quantity", "net quantity", "net qty"},
    "nav": {"nav", "purchase nav", "transaction nav", "price per unit", "unit price"},
    "avg_price": {"average buy price", "avg buy price", "average cost", "avg cost", "average purchase price", "buy average price", "average price", "avg price", "avg purchase price", "average cost per unit", "avg cost per unit", "purchase nav"},
    "current_price": {"current price", "ltp", "last traded price", "market price", "share price"},
    "symbol": {"symbol", "ticker", "stock symbol", "ticker symbol", "trading symbol"},
    "exchange": {"exchange", "market", "stock exchange"},
    "asset_type": {"asset type", "instrument type", "security type"},
    "amount": {"amount", "transaction amount", "invested amount", "investment amount", "invested value", "investment value", "cost value", "cost amount", "cost basis", "net amount", "gross amount", "purchase amount", "redemption amount", "buy value"},
    "current_value": {"current value", "market value", "valuation", "current valuation", "market valuation", "present value", "holding value"},
    "returns_value": {"returns", "return", "gain loss", "gain/loss", "profit loss", "profit/loss", "unrealized p&l", "unrealized pnl", "p&l", "pnl"},
    "xirr_pct": {"xirr", "xirr percent", "xirr %", "annualized return"},
    "transaction_date": {"date", "transaction date", "transaction date/time", "txn date", "trade date", "posting date"},
    "transaction_type": {"transaction type", "txn type", "type", "transaction", "description", "transaction details"},
    "snapshot_date": {"as of date", "as on date", "valuation date", "statement date", "portfolio date", "report date"},
}


def file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _header_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _header_map(row: list[object]) -> dict[str, int]:
    aliases = {_header_key(alias): key for key, values in HEADER_ALIASES.items() for alias in values}
    result = {}
    for index, value in enumerate(row):
        canonical = aliases.get(_header_key(value))
        if canonical and canonical not in result:
            result[canonical] = index
        if canonical == "scheme_name" and _header_key(value) in {_header_key(label) for label in ("stock name", "company name", "security name", "company", "stock", "scrip name")}:
            result["stock_name_header"] = index
        if canonical == "scheme_name" and _header_key(value) in {_header_key(label) for label in ("scheme", "scheme name", "fund name", "mutual fund", "mutual fund name")}:
            result["fund_name_header"] = index
    return result


def _normal_asset_type(value: object | None) -> str | None:
    text = _header_key(value)
    if any(term in text for term in ("stock", "equity", "share")):
        return "stock"
    if any(term in text for term in ("mutual fund", "scheme", "fund")):
        return "mutual_fund"
    return None


def _first_nonempty(row: list[object], index: int | None) -> object | None:
    if index is None or index >= len(row):
        return None
    value = row[index]
    if value is None or str(value).strip() == "":
        return None
    return value


def _date_value(value: object | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 1 <= value <= 100000:
        try:
            return xlrd.xldate_as_datetime(value, 0).date()
        except (ValueError, OverflowError):
            return None
    if value is None:
        return None
    text = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", str(value).strip(), flags=re.I)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _decimal_value(value: object | None, warnings: list[str], label: str) -> Decimal | None:
    if value is None or str(value).strip() in ("", "-", "—", "N/A", "NA"):
        return None
    text = str(value).strip().replace(",", "").replace("₹", "").replace("INR", "").replace("Rs.", "").replace("Rs", "").replace("%", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation:
        warnings.append(f"Could not read {label} value: {str(value)[:40]}")
        return None


def _transaction_type(value: object | None) -> str | None:
    text = str(value or "").casefold()
    if any(term in text for term in ("redemption", "withdrawal", "switch out", "repurchase", "sell")):
        return "SELL"
    if any(term in text for term in ("dividend", "idcw payout", "income distribution")):
        return "DIVIDEND"
    if any(term in text for term in ("fee", "charge", "stamp duty")):
        return "FEE"
    if any(term in text for term in ("purchase", "switch in", "investment", "allotment", "sip", "buy", "subscription")):
        return "BUY"
    return None


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _cell(row: list[object], header: dict[str, int], key: str):
    return _first_nonempty(row, header.get(key))


def _records_from_grid(grid: list[list[object]], file_type: str) -> list[dict]:
    if len(grid) > 10030:
        raise ImportParseError("The statement exceeds the 10,000-row processing limit. Split it into smaller files.")
    header_index = None
    header = {}
    groww_section = next((i for i, row in enumerate(grid) if any("holdings as on" in str(cell or "").casefold() for cell in row)), None)
    scan_start = groww_section + 1 if groww_section is not None else 0
    marker_date = None
    if groww_section is not None:
        for cell in grid[groww_section]:
            text = str(cell or "")
            match = re.search(r"HOLDINGS AS ON\s*[:\-]?\s*(.*)", text, re.I)
            marker_date = _date_value(match.group(1)) if match and match.group(1).strip() else marker_date
            marker_date = marker_date or _date_value(cell)
        if marker_date is None and groww_section + 1 < len(grid):
            marker_date = next((_date_value(cell) for cell in grid[groww_section + 1] if _date_value(cell)), None)
    for index, row in enumerate(grid[scan_start:]):
        candidate = _header_map(row)
        if "scheme_name" in candidate and "units" in candidate:
            header_index, header = index + scan_start, candidate
            break
    if header_index is None:
        mapped_headers = set().union(*(_header_map(row).keys() for row in grid)) if grid else set()
        missing = []
        if "scheme_name" not in mapped_headers:
            missing.append("a stock/company or mutual-fund scheme name")
        if "units" not in mapped_headers:
            missing.append("a quantity, shares, or units column")
        raise ImportParseError(f"Could not identify import columns. The statement needs {' and '.join(missing) or 'a recognizable holdings header row'}. Supported files may contain stocks, mutual funds, or both.")

    records = []
    for row_index, row in enumerate(grid[header_index + 1:], start=header_index + 2):
        scheme_name = _text(_cell(row, header, "scheme_name"))
        if not scheme_name:
            continue
        warnings = []
        raw_type = _cell(row, header, "transaction_type")
        transaction_type = _transaction_type(raw_type)
        transaction_date = _date_value(_cell(row, header, "transaction_date"))
        snapshot_date = _date_value(_cell(row, header, "snapshot_date")) or (marker_date if groww_section is not None else None)
        units = _decimal_value(_cell(row, header, "units"), warnings, "units")
        nav = _decimal_value(_cell(row, header, "nav"), warnings, "NAV")
        avg_price = _decimal_value(_cell(row, header, "avg_price"), warnings, "average buy price")
        current_price = _decimal_value(_cell(row, header, "current_price"), warnings, "current price")
        amount = _decimal_value(_cell(row, header, "amount"), warnings, "amount")
        current_value = _decimal_value(_cell(row, header, "current_value"), warnings, "current value")
        returns_value = _decimal_value(_cell(row, header, "returns_value"), warnings, "returns")
        xirr_pct = _decimal_value(_cell(row, header, "xirr_pct"), warnings, "XIRR")
        sources = {}
        for field, column in (("units", "units"), ("average_cost", "avg_price"), ("current_price", "current_price"), ("invested_value", "amount"), ("current_value", "current_value"), ("profit_loss", "returns_value")):
            if header.get(column) is not None and _cell(row, header, column) is not None:
                sources[field] = "statement"
        isin = _text(_cell(row, header, "isin"))
        if isin:
            isin = isin.upper()
        scheme_code_value = _decimal_value(_cell(row, header, "scheme_code"), warnings, "scheme code")
        scheme_code = int(scheme_code_value) if scheme_code_value and scheme_code_value == scheme_code_value.to_integral_value() else None
        symbol = _text(_cell(row, header, "symbol"))
        exchange = _text(_cell(row, header, "exchange"))
        explicit_type = _normal_asset_type(_cell(row, header, "asset_type"))
        has_fund_identity = bool(_cell(row, header, "amc_name") or _cell(row, header, "folio_number") or scheme_code)
        stock_signals = bool(symbol or exchange or header.get("stock_name_header") is not None or (avg_price is not None and not has_fund_identity) or (current_price is not None and not has_fund_identity))
        fund_signals = bool(has_fund_identity or header.get("nav") is not None or header.get("fund_name_header") is not None)
        asset_type = explicit_type or ("mutual_fund" if has_fund_identity or fund_signals and not stock_signals else "stock" if stock_signals else "ambiguous")
        if asset_type == "stock" and nav is None:
            nav = avg_price
        average_cost = avg_price if avg_price is not None else (nav if asset_type == "stock" else None)
        if current_price is None and asset_type == "mutual_fund":
            current_price = nav
            if current_price is not None:
                sources["current_price"] = "statement"
        if units is not None and units < 0:
            warnings.append("Units are negative; review the extracted quantity before importing.")
        if units == 0:
            warnings.append("Units are zero; enter a positive quantity before importing.")
        if amount is None and average_cost is not None and units is not None and units > 0:
            amount = average_cost * units
            sources["invested_value"] = "calculated"
        if average_cost is None and amount is not None and units is not None and units > 0:
            average_cost = amount / units
            sources["average_cost"] = "calculated"
        if current_price is None and current_value is not None and units is not None and units > 0:
            current_price = current_value / units
            sources["current_price"] = "calculated"
        if current_value is None and current_price is not None and units is not None:
            current_value = current_price * units
            sources["current_value"] = "calculated"
        if returns_value is None and current_value is not None and amount is not None:
            returns_value = current_value - amount
            sources["profit_loss"] = "calculated"
        record_type = "transaction" if asset_type == "mutual_fund" and (transaction_type or transaction_date) else "holding"
        if record_type == "transaction" and asset_type == "mutual_fund" and not isin and scheme_code is None:
            warnings.append("Add a valid scheme code or ISIN before importing this record.")
        if record_type == "holding":
            if snapshot_date is None:
                warnings.append("Add the statement as-of date before importing this holding.")
            if units is None:
                warnings.append("Units are missing or unreadable.")
        else:
            if transaction_type is None:
                warnings.append(f"Unrecognized transaction type: {str(raw_type or '')[:40]}")
            if transaction_date is None:
                warnings.append("Transaction date is missing or unreadable.")
            if transaction_type in ("BUY", "SELL") and units is None:
                warnings.append("Transaction units are missing or unreadable.")
            if transaction_type in ("BUY", "SELL") and nav is None and (amount is None or not units):
                warnings.append("A purchase/redemption needs NAV or amount and units.")
            if transaction_type in ("DIVIDEND", "FEE") and amount is None:
                warnings.append("Cash amount is missing or unreadable.")
        records.append({
            "row_id": row_index,
            "asset_type": asset_type,
            "record_type": record_type,
            "scheme_name": scheme_name[:240],
            "name": scheme_name[:240],
            "symbol": symbol.upper() if symbol else None,
            "exchange": exchange.upper() if exchange else None,
            "amc_name": _text(_cell(row, header, "amc_name")),
            "category": _text(_cell(row, header, "category")),
            "sub_category": _text(_cell(row, header, "sub_category")),
            "folio_number": _text(_cell(row, header, "folio_number")),
            "isin": isin,
            "scheme_code": scheme_code,
            "transaction_date": transaction_date.isoformat() if transaction_date else None,
            "transaction_type": transaction_type,
            "units": str(units) if units is not None else None,
            "quantity": str(units) if units is not None else None,
            "average_cost": str(average_cost) if average_cost is not None else None,
            "nav": str(nav) if nav is not None else None,
            "current_price": str(current_price) if current_price is not None else None,
            "amount": str(amount) if amount is not None else None,
            "invested_value": str(amount) if amount is not None else None,
            "current_value": str(current_value) if current_value is not None else None,
            "returns_value": str(returns_value) if returns_value is not None else None,
            "profit_loss": str(returns_value) if returns_value is not None else None,
            "xirr_pct": str(xirr_pct) if xirr_pct is not None else None,
            "snapshot_date": snapshot_date.isoformat() if snapshot_date else None,
            "as_of_date": snapshot_date.isoformat() if snapshot_date else None,
            "source_file_type": file_type,
            "field_sources": sources,
            "extraction_status": "review_required" if warnings else "ready",
            "warnings": warnings,
            "duplicate": False,
        })
    if not records:
        raise ImportParseError("The file contains a recognized header but no mutual-fund records.")
    return records


def _decode_csv(data: bytes) -> list[list[object]]:
    text = None
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ImportParseError("The CSV encoding is not supported. Save it as UTF-8 CSV and retry.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _excel_grids(data: bytes, extension: str) -> list[tuple[str, list[list[object]]]]:
    try:
        if extension == ".xlsx":
            workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            result = []
            for sheet in workbook.worksheets:
                rows = [list(row) for row in itertools.islice(sheet.iter_rows(max_col=200, values_only=True), 10031)]
                if any("scheme_name" in _header_map(row) and "units" in _header_map(row) for row in rows[:100]):
                    if len(rows) > 10030:
                        raise ImportParseError("The statement exceeds the 10,000-row processing limit. Split it into smaller files.")
                    result.append((sheet.title, rows))
            workbook.close()
            return result
        workbook = xlrd.open_workbook(file_contents=data, on_demand=True)
        result = []
        for sheet in workbook.sheets():
            rows = [sheet.row_values(row) for row in range(min(sheet.nrows, 10031))]
            if any("scheme_name" in _header_map(row) and "units" in _header_map(row) for row in rows[:100]):
                if sheet.nrows > 10030:
                    raise ImportParseError("The statement exceeds the 10,000-row processing limit. Split it into smaller files.")
                result.append((sheet.name, rows))
        workbook.release_resources()
        return result
    except ImportParseError:
        raise
    except Exception as exc:
        raise ImportParseError("Could not read this spreadsheet. Check that the workbook is valid and not encrypted.") from exc


def _pdf_grid(data: bytes, password: str | None) -> list[list[object]]:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ImportParseError("The PDF file could not be opened. It may be damaged or not a real PDF.") from exc
    try:
        if document.needs_pass:
            if not password:
                raise PasswordRequired("This PDF is password-protected. Enter its password to continue.")
            if not document.authenticate(password):
                raise IncorrectPdfPassword("That PDF password was not accepted. Check it and try again.")
        page_texts = [page.get_text("text") for page in document]
        if sum(len(text.strip()) for text in page_texts) < 40:
            if not shutil.which("tesseract"):
                raise ImportParseError("This PDF appears to be scanned. Install Tesseract OCR and retry, or use a text-based statement/CSV export.")
            import pytesseract

            page_texts = []
            for page in document:
                pixmap = page.get_pixmap(dpi=220, alpha=False)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                page_texts.append(pytesseract.image_to_string(image))
        text = "\n".join(page_texts)
        grid = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            cells = [cell.strip() for cell in re.split(r"\t+|\s{2,}|\s*\|\s*", line) if cell.strip()]
            if len(cells) > 1:
                grid.append(cells)
        return grid
    finally:
        document.close()


def parse_statement(data: bytes, filename: str, password: str | None = None) -> tuple[str, list[dict]]:
    extension = Path(filename or "").suffix.casefold()
    if extension not in SUPPORTED:
        raise ImportParseError("Unsupported file type. Upload a PDF, CSV, XLSX, or XLS statement.")
    if not data:
        raise ImportParseError("The selected file is empty.")
    if len(data) > MAX_IMPORT_BYTES:
        raise ImportParseError("File exceeds the 15 MB upload limit.")
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ImportParseError("The selected file does not have a valid PDF signature.")
        grids = [(None, _pdf_grid(data, password))]
    elif extension == ".csv":
        if data.startswith((b"%PDF-", b"PK\x03\x04")):
            raise ImportParseError("The file contents do not match the .csv extension.")
        grids = [(None, _decode_csv(data))]
    elif extension == ".xlsx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ImportParseError("The file contents do not match a valid .xlsx workbook.")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > 10000 or sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                raise ImportParseError("The spreadsheet expands beyond the safe processing limit.")
        grids = _excel_grids(data, extension)
    else:
        if not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise ImportParseError("The file contents do not match a valid .xls workbook.")
        grids = _excel_grids(data, extension)
    file_type = extension[1:]
    if not grids:
        raise ImportParseError("No worksheet contains recognizable holdings columns. Add a name and quantity/units column.")
    records = []
    for sheet_name, grid in grids:
        try:
            sheet_records = _records_from_grid(grid, file_type)
        except ImportParseError:
            if sheet_name is None:
                raise
            continue
        if sheet_name:
            for record in sheet_records:
                record["source_sheet"] = sheet_name
        records.extend(sheet_records)
    if not records:
        raise ImportParseError("No worksheet contains recognizable holdings records. Add a name and quantity/units column.")
    seen = set()
    for record in records:
        if record["record_type"] == "transaction" and record["transaction_type"] and record["transaction_date"]:
            key = tuple(record.get(name) for name in ("asset_type", "isin", "scheme_code", "transaction_type", "transaction_date", "units", "nav", "amount"))
        elif record["record_type"] == "holding":
            identity = record.get("symbol") or record.get("scheme_code") or record.get("isin") or _header_key(record.get("scheme_name"))
            key = tuple((record.get(name) for name in ("asset_type",))) + (identity, record.get("exchange"), record.get("folio_number"), record.get("snapshot_date"), record.get("units"), record.get("amount"), record.get("current_value"))
        else:
            continue
        if key in seen:
            record["duplicate"] = True
            record["warnings"].append(f"This {record['asset_type'].replace('_', ' ')} row appears more than once in the uploaded file.")
            record["extraction_status"] = "review_required"
        seen.add(key)
    return file_type, records
