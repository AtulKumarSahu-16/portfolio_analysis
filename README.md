# Portfolio Intelligence AI

React + FastAPI application for Indian stock quotes/history, mutual-fund NAV data, and a private investment portfolio ledger. FastAPI is the only component that talks to IndianAPI and MFNAV. PostgreSQL stores user accounts, portfolios, transactions, planned SIP schedules, a bounded-by-expiry provider-response cache, and a 30-day operational request log.

## Local setup

Requirements: Python 3.11+, Node.js 20.19+ (or 22.12+), npm, and a local PostgreSQL server. Docker is optional.

1. Start your local PostgreSQL server and create a database and role matching `DATABASE_URL` in `backend/.env`. Docker is optional; if you prefer Docker, start the bundled database with:

   ```sh
   docker compose up -d db
   ```

2. In a terminal, configure and start FastAPI:

   ```sh
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   # Create .env only if you don't already have one:
   test -f .env || cp .env.example .env
# Ensure DATABASE_URL points to your local PostgreSQL database and set a private JWT_SECRET_KEY (32+ random characters).
# Add your IndianAPI key/base URL when available; the key is optional for account and portfolio entry.
   alembic upgrade head
   uvicorn app.main:app --reload
   ```

3. In a second terminal, start React:

   ```sh
   cd frontend
   npm install
   npm run dev
   ```

Open the Vite URL shown in the terminal (usually http://localhost:5173). The Vite dev server forwards `/api` and `/health` to FastAPI at `http://localhost:8000`.

## Provider configuration

Set `INDIANAPI_API_KEY` only in `backend/.env`. Never use a `VITE_` variable for provider credentials. Set `INDIANAPI_BASE_URL` to the URL for the active plan: `https://stock.indianapi.in` for Free/Hobby, `https://dev.indianapi.in` for Developer, `https://analyst.indianapi.in` for Growth Analyst, or `https://pro.indianapi.in` for Pro. The provider's plan dashboard is authoritative for your current request credits and limits. MFNAV currently requires no key for documented endpoints; `MFNAV_BASE_URL` defaults to `https://mfnav.in`.

`DATABASE_URL` defaults to the local Compose database. For a Homebrew/local PostgreSQL server, update the username, password, host, port, and database in `backend/.env`. Cache TTLs and the finite upstream timeout are configurable in the same file. `JWT_SECRET_KEY` signs the HttpOnly session cookie; `AUTH_COOKIE_SECURE` should be `true` behind HTTPS in deployment. Apply schema changes with Alembic before starting FastAPI; startup checks the database connection and does not create or alter tables.

Create an account at `/signup`, then sign in at `/login`. Account sessions use a backend-signed, HttpOnly cookie; passwords are hashed with Argon2. The dashboard shows imported holdings and their cost basis. Create a portfolio from Import Portfolio, then upload a PDF, CSV, XLSX, or XLS statement, review/edit the extracted values and confirm the import. Market values appear only when a provider returns a real quote/NAV or the statement supplies a current value; unavailable data stays unavailable.

Use **Import Portfolio** in the sidebar to preview stock, mutual-fund, or mixed holdings statements, review/edit extracted rows, and confirm import. Supported files are PDF, CSV, XLSX, and XLS up to 15 MB. Stock matching and quotes reuse the configured IndianAPI key from `backend/.env`; mutual-fund matching uses the existing MFNAV/AMFI scheme master. Text PDFs and password-protected PDFs are supported; scanned PDFs use OCR if the Tesseract executable is installed. The upload and password are processed for the current request only; uploaded source files and passwords are not saved. Review each row carefully. See [statement import guide](docs/Statement_Import.md).

The authenticated workspace includes stock lookup and price history, mutual-fund search and NAV history, portfolio performance snapshots, provider-classified direct-stock industries, fundamentals and financial news summaries, portfolio CSV exports, and data-grounded portfolio Q&A. News language labels use a lightweight word-match heuristic. Portfolio Q&A is deterministic and does not use a generative AI provider.

The Overlap Analysis page lets you enter dated large-, mid-, small-cap, and commodity allocations from each held fund's AMC/AMFI disclosure and compares shared category percentages. MFNAV does not supply those figures, so enter actual disclosed values with their source and date. This is category-allocation similarity, not underlying-security overlap; mutual-fund sector look-through remains unavailable. Performance is a current valuation snapshot from the transaction ledger, not an annualized or time-weighted return. See the [architecture notes](docs/Architecture.md) for current feature boundaries.

## API verification

Visit http://localhost:8000/docs and http://localhost:8000/health. Example requests:

```sh
curl http://localhost:8000/api/stocks/INFY/price
curl 'http://localhost:8000/api/stocks/INFY/history?period=1yr'
curl 'http://localhost:8000/api/mutual-funds/search?q=hdfc&page_size=10'
curl http://localhost:8000/api/mutual-funds/100641/nav
curl 'http://localhost:8000/api/mutual-funds/100641/history?start_date=2025-01-01&end_date=2025-12-31'
```

Stock calls require a valid IndianAPI key and a plan that permits the selected host/endpoint. A missing or rejected credential returns a safe error, not sample market data. Tests use mocked provider responses and SQLite; they do not prove live provider access.

After signing in, portfolio endpoints use the session cookie. For example, `GET /api/portfolios` lists the current user's portfolios, and `GET /api/portfolios/{id}/holdings` returns transaction-derived units, cost basis, and provider valuations where available. `POST /api/portfolios/{id}/transactions` records a purchase. The browser sends same-origin `/api` requests; provider keys remain in the backend environment. See the API notes for the full portfolio route list.

## Tests

```sh
cd backend
source .venv/bin/activate
pytest -q
```

The tests cover response mapping, caching, invalid inputs, rate limits, and timeouts. See [API integration notes](docs/API_Integration.md) for route shapes and provider details.

See [architecture notes](docs/Architecture.md) for the new Stage 1 account and portfolio schema and its migration workflow.
