import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

if os.environ.get("TESTING"):
    if not settings.TEST_DATABASE_URL:
        raise RuntimeError("TESTING is set but TEST_DATABASE_URL is not configured")
    DATABASE_URL = settings.TEST_DATABASE_URL
else:
    DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=settings.DB_ECHO)

AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=False)
