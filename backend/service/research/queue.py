"""Database queue operations shared by API and worker."""

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.research_models import ResearchRun

ACTIVE = ("queued", "running")


async def expire_runs(db: AsyncSession) -> None:
    now = datetime.utcnow()
    await db.execute(
        update(ResearchRun)
        .where(
            or_(
                and_(ResearchRun.status == "running", ResearchRun.lease_expires_at < now),
                and_(
                    ResearchRun.status == "running",
                    ResearchRun.started_at
                    < now - timedelta(seconds=settings.RESEARCH_TIMEOUT_SECONDS),
                ),
                and_(
                    ResearchRun.status == "queued",
                    ResearchRun.created_at
                    < now - timedelta(seconds=settings.RESEARCH_TIMEOUT_SECONDS),
                ),
            )
        )
        .values(
            status="failed",
            stage="Research interrupted",
            error="The worker stopped or the research deadline expired. Check the worker and retry.",
            finished_at=now,
            lease_expires_at=None,
        )
    )


async def claim_run(db: AsyncSession, worker_id: str) -> str | None:
    await expire_runs(db)
    run = await db.scalar(
        select(ResearchRun)
        .where(ResearchRun.status == "queued")
        .order_by(ResearchRun.created_at, ResearchRun.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        await db.commit()
        return None
    run_id = run.id
    now = datetime.utcnow()
    run.status = "running"
    run.stage = "Reviewing your question"
    run.worker_id = worker_id
    run.started_at = now
    run.lease_expires_at = now + timedelta(seconds=settings.RESEARCH_LEASE_SECONDS)
    await db.commit()
    return run_id
