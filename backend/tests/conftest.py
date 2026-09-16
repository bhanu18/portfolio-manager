import asyncio
import os
import sys
from typing import Any, AsyncGenerator

import pytest_asyncio
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# --- Add project root to path ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["TESTING"] = "1"

from main import app
from db.dependencies import get_db
from db.orm_models import Base
from core.config import settings


# This fixture creates a new event loop for the entire test session.
@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# This fixture sets up and tears down the database schema once per session.
@pytest_asyncio.fixture(scope="session", autouse=True)
def setup_test_db():
    """
    Set up the test database by running Alembic migrations before any tests run,
    and downgrading after all tests have finished.
    """
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)

    # Apply all migrations
    command.upgrade(alembic_cfg, "head")
    yield
    # Downgrade the database to the base state
    command.downgrade(alembic_cfg, "base")


# --- THIS IS THE NEW, CORRECT FIXTURE FOR THE CLIENT ---
@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[TestClient, Any]:
    """
    Provides a TestClient with a transactional database session for each test.
    The transaction is rolled back after the test.
    """
    engine = create_async_engine(settings.TEST_DATABASE_URL)

    async with engine.connect() as connection:
        async with connection.begin() as transaction:
            TestingSessionLocal = sessionmaker(
                bind=connection, class_=AsyncSession, expire_on_commit=False
            )
            db_session = TestingSessionLocal()

            async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
                yield db_session

            app.dependency_overrides[get_db] = override_get_db

            # Yield the TestClient to the test function
            with TestClient(app) as c:
                yield c

            # The transaction is automatically rolled back when the `async with` block exits.
            # No need for an explicit rollback call unless there's an error to handle.

    app.dependency_overrides.clear()
    await engine.dispose()
