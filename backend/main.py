import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from core.config import settings
from db.session import engine
from routers import assets, auth, email, group, reports, trades

# Rate limiter keyed by client IP
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing to do. Migrations are run explicitly with `alembic upgrade head`.
    yield
    # Shutdown: release pooled DB connections
    await engine.dispose()


app = FastAPI(
    title="Portfolio Manager API",
    description=(
        "Multi-currency stock & crypto portfolio tracker. "
        "Manage assets and trades, share portfolios through groups, "
        "and get valuation, FX and risk-adjusted performance reports."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.include_router(trades.router)
app.include_router(reports.router)
app.include_router(auth.router)
app.include_router(group.router)
app.include_router(email.router)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add an X-Process-Time header with the request duration in seconds."""
    start_time = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{time.perf_counter() - start_time:.4f}"
    return response


@app.get("/", tags=["meta"])
async def read_root():
    """API landing endpoint."""
    return {
        "name": app.title,
        "version": app.version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["meta"])
async def health():
    """Liveness + database connectivity check."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unavailable"
    return {"status": "ok" if db_status == "ok" else "degraded", "database": db_status}
