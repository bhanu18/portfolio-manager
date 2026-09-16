"""
Test fixtures.

Requires TEST_DATABASE_URL (async MySQL URL) pointing at a disposable database.
Schema is created once per session with Alembic; each test runs inside a
transaction that is rolled back, so tests never see each other's data.
"""

import os
import sys
from collections.abc import AsyncGenerator, Generator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["TESTING"] = "1"

from core.config import settings
from db.dependencies import get_db
from main import app
from routers import auth as auth_router
from routers import email as email_router

if not settings.TEST_DATABASE_URL:
    pytest.exit("TEST_DATABASE_URL must be set to run the test suite", returncode=2)

TEST_ASYNC_URL = settings.TEST_DATABASE_URL
TEST_SYNC_URL = (
    make_url(TEST_ASYNC_URL).set(drivername="mysql+pymysql").render_as_string(hide_password=False)
)

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _drop_all_tables(url: str) -> None:
    """Wipe the test database (reflect + drop), independent of migration downgrades."""
    engine = create_engine(url, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        meta = MetaData()
        meta.reflect(bind=conn)
        meta.drop_all(bind=conn)
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrate_test_db() -> Generator[None, None, None]:
    """Start from an empty test database and apply all migrations once per session."""
    _drop_all_tables(TEST_SYNC_URL)
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_SYNC_URL)
    command.upgrade(cfg, "head")
    yield
    _drop_all_tables(TEST_SYNC_URL)


@pytest.fixture(autouse=True)
def disable_rate_limits() -> Generator[None, None, None]:
    """slowapi limits (e.g. 3 registrations/hour) would make tests order-dependent."""
    limiters = [auth_router.limiter, email_router.limiter, app.state.limiter]
    for limiter in limiters:
        limiter.enabled = False
    yield
    for limiter in limiters:
        limiter.enabled = True


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A session bound to an outer transaction that is rolled back after the test."""
    engine = create_async_engine(TEST_ASYNC_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",  # app commits become savepoints
        )
        async with session_factory() as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client that talks to the app in-process, using the test session."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
