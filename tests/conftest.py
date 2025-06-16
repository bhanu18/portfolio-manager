import pytest
import os
import sys
from typing import Generator, Any, AsyncGenerator
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set the TESTING environment variable before any other imports
os.environ['TESTING'] = '1'

from main import app # Import your FastAPI app
from db.session import engine
from db.orm_models import Base
from db.dependencies import get_db
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession


# Create a separate Test Session factory
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession
)

# This fixture runs once for the entire test session
@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    # Create all database tables
    async def setup_db_async():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    import asyncio
    asyncio.run(setup_db_async())
    
    yield # The tests run here
    
    # Teardown: Drop all database tables
    async def teardown_db_async():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    
    asyncio.run(teardown_db_async())


# This fixture provides a database session for a single test
@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session

# This fixture provides an API client for making requests
@pytest.fixture(scope="function")
def client(db_session: AsyncSession) -> Generator[TestClient, Any, None]:
    """
    Create a new TestClient that uses the test database for the duration of a test.
    """
    def override_get_db():
        try:
            yield db_session
        finally:
            pass # The session is managed by the db_session fixture

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c