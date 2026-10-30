# Market data API integration

FastAPI is the browser's only market-data entry point. Provider credentials stay on the backend. The frontend uses relative `/api` paths; Vite proxies them to FastAPI during local development.

## Application endpoints

| Method and path | Parameters | Provider |
|---|---|---|
| `POST /api/auth/signup` | JSON: `display_name`, `email`, `password` (12–128 chars) | Local account database |
| `POST /api/auth/login` | JSON: `email`, `password` | Local account database |
| `POST /api/auth/logout` | No request fields | Clears the session cookie |
| `GET /api/auth/me` | Requires the session cookie | Local account database |
| `GET /api/portfolios` | Requires the session cookie | PostgreSQL; current user's portfolios |
| `POST /api/portfolios` | JSON: `name` | Creates a portfolio for the current user |
| `GET /api/portfolios/{portfolio_id}/transactions` | `page`, `page_size` | PostgreSQL; owner-scoped ledger |
| `POST /api/portfolios/{portfolio_id}/transactions` | JSON transaction and instrument; optional `sip_schedule` | PostgreSQL; creates instrument identity as needed |
| `PUT /api/portfolios/{portfolio_id}/transactions/{transaction_id}` | JSON editable transaction fields | PostgreSQL; owner-scoped update |
| `DELETE /api/portfolios/{portfolio_id}/transactions/{transaction_id}` | No request fields | PostgreSQL; owner-scoped delete |
| `GET /api/portfolios/{portfolio_id}/sip-schedules` | None | PostgreSQL; saved planned contributions |
| `GET /api/portfolios/{portfolio_id}/holdings` | None | Ledger and imported snapshots, distinct by folio; IndianAPI/MFNAV current price/NAV where identity is available |
| `GET /api/portfolios/{portfolio_id}/fund-allocations` | None | Latest saved category allocation per held mutual fund |
| `POST /api/portfolios/{portfolio_id}/fund-allocations` | Dated allocation values and a source label; optional URL | Saves or replaces one fund's allocation snapshot for that date |
| `GET /api/portfolios/{portfolio_id}/fund-allocations/overlap` | None | Pairwise large-, mid-, small-cap, and commodity allocation comparison |
| `POST /api/portfolios/{portfolio_id}/imports/preview` | Multipart: `file`; optional one-request `password` | Extracts PDF/CSV/XLSX/XLS rows for review; creates no investment records |
| `POST /api/portfolios/{portfolio_id}/imports/confirm` | JSON: `import_id`, reviewed `records` | Saves dated transactions and/or current holding snapshots; deduplicates |
| `GET /api/portfolios/{portfolio_id}/imports` | None | Owner-scoped import history and row counts |
| `DELETE /api/portfolios/{portfolio_id}/imports/{import_id}` | Pending preview only | Cancels a preview without importing investment records |
| `GET /api/stocks/{symbol}/price` | Company name or ticker path value | IndianAPI `/stock?name=...` |
| `GET /api/stocks/{symbol}/history` | `period`: `1m`, `6m`, `1yr`, `3yr`, `5yr`, `10yr`, `max` | IndianAPI `/historical_data?stock_name=...&period=...&filter=price` |
| `GET /api/mutual-funds/search` | Required `q` (2–120 chars); `page`, `page_size` (1–500) | MFNAV `/api/funds/search` |
| `GET /api/mutual-funds/{scheme_code}/nav` | Positive scheme code | MFNAV `/api/funds/{scheme_code}`; normalized from `latest_nav` and `latest_nav_date` |
| `GET /api/mutual-funds/{scheme_code}/history` | Optional `start_date`, `end_date`; `page`, `page_size` (1–10000) | MFNAV `/api/nav/{scheme_code}` |

Stock price response keeps provider fields under `market_data` with `source` and requested `symbol`. Stock history returns the provider's price series and normalized date/price `points`. NAV history preserves MFNAV's `fund_details`, `data`, and pagination fields alongside `source`. Latest NAV returns `nav` and `nav_date` as supplied by MFNAV. Error responses do not include upstream headers, credentials, or raw provider error bodies.

Signup/login set an `HttpOnly`, `SameSite=Lax` cookie scoped to `/api`; JavaScript cannot read the session token. Local development defaults `AUTH_COOKIE_SECURE=false`; deployments must use HTTPS and set it to `true`. Keep `JWT_SECRET_KEY` private and at least 32 random characters. Portfolio routes are authenticated and owner-scoped. Add and verify CSRF/origin protection before exposing authenticated write routes to cross-origin clients or public deployment.

Portfolio `POST` and `PUT` payloads are validated by schemas in `backend/app/schemas/portfolio.py`. A transaction uses `side` (`BUY` or `SELL`), `trade_date`, positive `quantity`, positive `price_per_unit`, optional nonnegative `fees`, and an `instrument` object. Stocks require a symbol and exchange; mutual funds require a scheme code. An optional SIP schedule can be included when creating a fund purchase. The schedule records intent only; installments are not automatically booked. A sale that exceeds the units held on that date returns HTTP 422. Portfolio ownership failures return 404.

The holdings response derives units and cost basis from the saved ledger. Current values are returned only when an upstream provider returns a usable quote or NAV; unavailable valuations are marked rather than replaced with sample prices.

Statement import limits are 15 MB and 10,000 records per file. Sources are parsed in memory; the app stores only a SHA-256 file fingerprint and import status/count metadata, not the original statement. Confirmed transaction rows link to an import batch; current-position rows are dated snapshots and act as a ledger baseline. Groww `HOLDINGS AS ON` Excel sections are supported without requiring ISIN. MFNAV exact name plus AMC matches can resolve the scheme; unmatched holdings remain explicitly unverified, and folio numbers are represented in storage by a hash with only the last four digits displayed. See [the import guide](Statement_Import.md) for accepted fields, review rules, OCR setup, and known parser limits.

Fund category allocations are entered from an AMC/AMFI disclosure by the signed-in user because the configured MFNAV API supplies NAV and scheme data, not these allocation percentages. The saved record includes a disclosure date, source label, and optional source URL. Percentages are constrained to 0–100, their total cannot exceed 100, and at least one category must be supplied. Pairwise shared allocation is `min(fund A category %, fund B category %)` and is returned only when both saved snapshots use the same date. This measures cap/commodity allocation similarity; it is not security-level portfolio overlap.

## Persistence and caching

SQLAlchemy async models use PostgreSQL in normal operation. `cached_responses` stores successful JSON responses until their TTL expires; expired rows are pruned on cache writes and stale entries are removed on read. Stock quotes default to 60 seconds; NAV search/details to 1 hour; history to 1 hour. `market_data_requests` stores provider name, application route label, status, cache-hit flag, and timestamp for 30 days; it does not store query strings, credentials, or response bodies. The schema defines users, portfolios, instruments, transactions, and SIP schedules. Stage 2 adds account registration and sessions; Stage 3 adds the owner-scoped portfolio ledger and dashboard workflow. This cache is shared across backend workers using the same database. Set a TTL to zero to disable caching for that response class.

The test suite substitutes SQLite and mocked HTTP responses. Do not interpret those tests as live data checks. IndianAPI key and plan must be configured independently for real stock requests.

## Verified provider constraints

- IndianAPI authenticates with the `x-api-key` header (HTTP header names are case-insensitive; the backend sends `X-API-Key`). Free/Hobby use `https://stock.indianapi.in`; Developer, Growth Analyst, and Pro plans use `dev`, `analyst`, and `pro` hosts respectively. Free plan access exists, but quota varies by plan and must be checked in the provider dashboard. The stock-details endpoint uses `/stock?name=...`; historical data uses `/historical_data?stock_name=...&period=...&filter=price`. Confirm access against the account's actual plan.
- MFNAV documents anonymous access without a key and a 120-request/minute/IP limit. Scheme details can return HTTP 409 for ambiguous shared ISINs; this app's routes use scheme codes to avoid selecting an ambiguous ISIN. MFNAV NAV values are daily and may be dated before the current calendar day.
- Prices may be delayed and stale outside market hours. The app does not claim real-time freshness when the provider response does not establish it.

Official references: [IndianAPI developer docs](https://dev.indianapi.in/), [Indian Stock Market API documentation](https://indianapi.in/documentation/indian-stock-market), [IndianAPI plan and pricing page](https://indianapi.in/indian-stock-market), [MFNAV API docs](https://mfnav.in/api-docs), [MFNAV OpenAPI](https://mfnav.in/openapi.json).
