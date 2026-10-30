import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import Base


@pytest_asyncio.fixture
async def api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override():
        async with sessions() as session:
            yield session

    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", indianapi_api_key="test-key", indianapi_base_url="https://stock.indianapi.in", mfnav_base_url="https://mfnav.in", jwt_secret_key="test-secret-for-unit-tests-long-enough")
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    await app.state.http.aclose()
    app.dependency_overrides.clear()
    await engine.dispose()


async def mock_provider(app, handler):
    import httpx
    await app.state.http.aclose()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(0.1))
