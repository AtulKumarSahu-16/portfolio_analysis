# Portfolio statement import

## User flow

Open **Import Portfolio** in the authenticated sidebar. Create a portfolio if needed, then select a PDF, CSV, XLSX, or XLS file (maximum 15 MB), wait for preview, correct the extracted rows, remove unwanted rows, then confirm. Cancel removes the pending preview and imports no investment rows. Statement import is the portfolio entry workflow.

PDF files may require a password. The password field appears only after the backend detects encryption. Passwords are sent in the preview request, are not written to the database or logs, and are cleared from the React page after successful processing. A wrong password returns an error and allows another attempt. Scanned PDFs use OCR only when extracted text is insufficient. Install the Tesseract executable to enable OCR; without it, the API gives a setup message and the user can retry with a text PDF or spreadsheet.

The source file is read into a bounded request buffer and processed in memory. The framework may use a temporary spooled upload buffer during the request, which is closed after processing; the app does not retain the source file or expose it as a URL. Database import history stores a SHA-256 file fingerprint and counts/status, not the file name or contents. Confirmed transactions and holding snapshots are retained because they become part of the user's portfolio data.

## Recognized data

The parser searches for a header row and accepts common variations for stock/company/security name, ticker, exchange, average buy price/cost, current price/LTP, mutual-fund scheme, AMC/fund house, category, folio, scheme code, ISIN, quantity/units, NAV, invested/current value, returns/P&L, XIRR, transaction date/type, and statement as-of date. It detects asset type per row, allowing stock-only, fund-only, or mixed holdings sheets. Groww Excel workbooks are detected by the `HOLDINGS AS ON` section and that date is used for the holdings snapshot. It parses common date forms and numeric values with commas, rupee symbols, percentages, and parentheses. Unrecognized or unreadable fields become warnings for review; missing values can be corrected in the preview.

For a current-holdings row, add the statement as-of date if it was not extracted. Units are required; current price/value, returns, XIRR, and invested amount can be corrected in preview. Holdings snapshots are not turned into fake dated purchases. A missing ISIN does not block a holding. Mutual-fund preview matches against the existing MFNAV/AMFI scheme master using name and AMC; it auto-selects only when both match exactly. Candidate matches can be selected from a dropdown, and unmatched rows can be imported as unverified with no ISIN/scheme code. Live NAV is unavailable for unverified funds until their identity is resolved. Stock rows use the configured IndianAPI stock service to match the supplied symbol or company name and fetch available quote data. A failed or unmatched lookup leaves the row editable and importable as unverified; the statement value is retained.

Stock identity is stored using the existing `Instrument` stock fields (name, symbol, exchange, optional ISIN). Imported snapshots retain units, average buy price, invested value, current price, current value, and returns. Alembic revision `0005_imported_stock_prices` adds nullable average-buy and current-price fields to existing snapshot rows; no portfolio records are removed.

Folio values are used to keep same-scheme positions distinct. The raw folio is not stored; the database keeps a one-way SHA-256 reference and displays only its last four characters.

For a transaction row, purchases/redemptions need a date, units, and NAV or an amount from which unit price can be derived. Dividends/fees need a date and amount. Fund identity must have a scheme code or valid ISIN; ISINs are resolved through MFNAV during confirmation. Ambiguous or invalid scheme identities need correction before import.

## Duplicate handling and endpoints

- Re-uploading the exact same file to the same portfolio is rejected using a SHA-256 fingerprint.
- Transaction rows already present in the ledger are skipped by instrument, type, date, units, and unit price/cash amount. Repeated transaction rows in one file are flagged during preview.
- Current holdings are stored as dated snapshots per scheme and folio. Re-importing a snapshot for the same scheme, folio, and as-of date skips it.
- Preview and history are scoped to the signed-in user's portfolio. Only a pending preview can be cancelled.

The endpoints are:

- `POST /api/portfolios/{portfolio_id}/imports/preview` — multipart `file`, optional one-request `password`.
- `POST /api/portfolios/{portfolio_id}/imports/confirm` — JSON reviewed records plus `import_id`.
- `GET /api/portfolios/{portfolio_id}/imports` — import history.
- `DELETE /api/portfolios/{portfolio_id}/imports/{import_id}` — cancel pending preview.

The processing limit is 10,000 rows. Excel workbooks are bounded by compressed upload size and a 100 MB expanded-size limit.

On macOS, install the optional OCR executable with `brew install tesseract`. PyMuPDF, Pillow, and pytesseract are installed from `backend/requirements.txt`; the `tesseract` executable itself is an operating-system dependency.

## Format limitations

This is a header-based parser and has not been verified against every broker workbook or eCAS statement. PDF table extraction varies by issuer, layout, and statement type. OCR output is especially error-prone, so review every row. Password conventions differ by issuer; the app does not guess passwords. Protected Excel files and unsupported headers need a different export. No external AI service receives statement contents. IndianAPI and MFNAV lookup failures leave holdings importable as unverified.

After changing the backend, apply migrations from `backend/`:

```sh
source .venv/bin/activate
alembic upgrade head
```

