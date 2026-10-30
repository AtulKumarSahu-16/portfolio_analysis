from contextlib import asynccontextmanager
import asyncio

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import mutual_funds, stocks
from app.api.routes import auth, portfolio, portfolio_import
from app.core.config import get_settings
from app.db import SessionLocal, engine
from app.services.market_data_scheduler import create_market_data_scheduler, run_startup_catchup, wait_for_refresh_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    settings = get_settings()
    connect_timeout = min(3.0, settings.http_timeout_seconds)
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=connect_timeout,
            read=settings.http_timeout_seconds,
            write=settings.http_timeout_seconds,
            pool=connect_timeout,
        )
    )
    app.state.settings = settings
    app.state.session_factory = SessionLocal
    scheduler = create_market_data_scheduler(app)
    scheduler.start()
    startup_refresh = asyncio.create_task(run_startup_catchup(app), name="market-data-startup-catchup")
    app.state.market_data_scheduler = scheduler
    yield
    scheduler.shutdown(wait=False)
    await asyncio.gather(startup_refresh, return_exceptions=True)
    await wait_for_refresh_jobs()
    await app.state.http.aclose()
    await engine.dispose()


app = FastAPI(title="Portfolio Intelligence AI API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"])
app.include_router(auth.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(portfolio_import.router, prefix="/api")
app.include_router(stocks.router, prefix="/api")
app.include_router(mutual_funds.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
