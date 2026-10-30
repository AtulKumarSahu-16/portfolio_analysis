# Architecture and database schema

## Current boundary

The provider-backed stock and mutual-fund routes remain the market-data boundary. React calls FastAPI, and FastAPI calls IndianAPI/MFNAV. PostgreSQL stores signed-in users and user-owned investments. Portfolio routes scope every portfolio lookup to the authenticated user.

## PostgreSQL entities

- `users`: normalized-at-service-layer email, password hash, display name, active flag, and timestamps. Passwords are never stored in plaintext.
- `portfolios`: user-owned named collections with currency (currently INR by default).
- `instruments`: canonical stock or mutual-fund identity, provider identifiers, exchange/symbol, scheme code, and ISIN. Provider identity is kept separate from a user’s transactions.
- `portfolio_transactions`: dated BUY/SELL entries use decimal quantity and per-unit price; DIVIDEND/FEE entries use a cash amount. Database checks reject invalid amount combinations and negative fees. Current holdings should be derived from the transaction ledger.
- `sip_schedules`: optional planned contribution schedule. A schedule is not treated as an executed investment; actual contributions must be recorded as transactions.
- `cached_responses` and `market_data_requests`: existing provider cache and short-retention operational records.

Portfolio and child rows use database foreign keys and cascade behavior. Service routes must enforce that every portfolio and transaction belongs to the authenticated user; the schema alone does not provide authorization.

## Migrations

Alembic owns schema changes. `backend/alembic/versions/0001_portfolio_schema.py` creates the initial account/portfolio tables and preserves the existing cache tables if an earlier local run created them. FastAPI checks database connectivity on startup but no longer silently creates or alters the schema.

From `backend/` after configuring `.env`:

```sh
alembic upgrade head
alembic current
```

Before applying any future downgrade in a database containing portfolio data, back up the database: the initial downgrade removes portfolio tables and their records.

## Stage 2 account and UI foundation

Account routes are `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, and authenticated `GET /api/auth/me`. Passwords use Argon2 hashes; signed sessions use an HttpOnly, SameSite cookie and require `JWT_SECRET_KEY`. The React app has a public landing page, signup/login screens, and a responsive authenticated shell.

## Stage 3 portfolio workflow

`backend/app/api/routes/portfolio.py` provides portfolio creation/listing, transaction list/create/update/delete, SIP schedule listing, and holdings valuation. Each route requires the session cookie. Reads and writes first verify portfolio ownership; unknown and other users' portfolio IDs return 404. A transaction ledger is the source for units and cost basis. A sale that would make units negative is rejected. Optional SIP schedules are plans only and do not generate future transactions.

The React `PortfolioProvider` loads a user's portfolios and selected portfolio. The Dashboard shows holdings, cost basis, and provider-backed current values. The Investments page records stock and mutual-fund purchases and supports transaction edits/deletions. Quote/NAV lookup is optional for recording a purchase. Current market values use IndianAPI/MFNAV responses and the shared SQLAlchemy cache; missing provider prices remain null and the dashboard identifies incomplete valuation. No sample user, portfolio, transaction, market value, or return is inserted.

The app's authenticated write routes currently rely on same-origin development proxying and cookie authentication. Before exposing the API to other origins or deploying it publicly, add and verify CSRF/origin protection for authenticated writes.

## Workspace analytics and research

The stock workspace uses the stock quote and historical-price routes. IndianAPI's stock-details response also supplies the profile, fundamentals, industry classification, and recent-news fields used by research and direct-stock sector screens when those fields are present. News tone is labeled with a simple word-match heuristic and is not an investment signal. Mutual-fund search and NAV history use MFNAV; performance is calculated as a current snapshot from ledger cost basis and provider valuation.

Reports are generated as CSV downloads from authenticated portfolio APIs in the browser. Portfolio Q&A returns deterministic summaries of the active portfolio; no external generative AI service or key is configured. MFNAV's current integration returns NAV and scheme search data, not verified underlying constituents and weights, so security-level fund overlap and mutual-fund look-through sector analysis are unavailable. The Overlap Analysis page accepts user-entered, dated allocation values from fund disclosures for category comparisons.

### Dated fund allocation comparison

`fund_allocation_snapshots` stores user-entered large-, mid-, and small-cap plus commodity allocation percentages for a held mutual fund, with the disclosure date and source. The Overlap Analysis page accepts these values from a fund-house/AMFI factsheet and displays latest saved values. For each pair and category it reports `min(allocation A, allocation B)` only when the snapshot dates match. This is a category allocation comparison, not constituent overlap. Data not disclosed by the source remains null. Apply the additive Alembic migration `0002_fund_allocation_snapshots` before using these routes.

### Statement import

`portfolio_imports` holds a per-portfolio SHA-256 file fingerprint, file type, status, and counts only; source statements, extracted folio values, and PDF passwords are not persisted. Confirmed dated buys/sells/dividends/fees become linked `portfolio_transactions`. Current position-only rows go into `imported_holding_snapshots` and are distinct from transaction history. Holdings use the latest snapshot as the starting position and apply ledger transactions dated after that snapshot, preventing double counting of transactions already reflected in the statement balance. Unknown imported cost basis stays null. Apply Alembic revision `0003_portfolio_statement_imports` before using import routes.
