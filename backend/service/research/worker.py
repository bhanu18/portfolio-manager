"""Run with `python -m service.research.worker` alongside the API."""

import asyncio
import contextlib
import json
import logging
import signal
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from core.config import settings
from core.time import db_utc_now
from db.research_models import ResearchMessage, ResearchRun, ResearchSession
from db.session import AsyncSessionLocal, engine
from service.research.agent import ResearchFailure
from service.research.configuration import model_for_provider, provider_enabled, provider_options
from service.research.orchestrator import FailoverResearchAgent, ResearchOrchestrator
from service.research.queue import claim_run
from service.research.usage import add_usage

logger = logging.getLogger(__name__)


async def save_progress(run_id: str, worker_id: str, **values: Any) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
        if run is None or run.status != "running" or run.worker_id != worker_id:
            raise asyncio.CancelledError
        if run.lease_expires_at is None or run.lease_expires_at < db_utc_now():
            raise asyncio.CancelledError
        for key, value in values.items():
            setattr(run, key, value)
        await db.commit()


async def heartbeat(run_id: str, worker_id: str, task: asyncio.Task) -> None:
    while not task.done():
        await asyncio.sleep(settings.RESEARCH_LEASE_SECONDS / 3)
        try:
            async with AsyncSessionLocal() as db:
                now = db_utc_now()
                result = await db.execute(
                    update(ResearchRun)
                    .where(
                        ResearchRun.id == run_id,
                        ResearchRun.status == "running",
                        ResearchRun.worker_id == worker_id,
                        ResearchRun.lease_expires_at >= now,
                    )
                    .values(
                        lease_expires_at=now + timedelta(seconds=settings.RESEARCH_LEASE_SECONDS)
                    )
                )
                await db.commit()
                if not result.rowcount:
                    task.cancel()
                    return
        except Exception:
            logger.exception("Research heartbeat failed for %s", run_id)
            task.cancel()
            return


async def finish(
    run_id: str, worker_id: str, *, report: str | None = None, error: str | None = None
) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
        if run is None or run.status != "running" or run.worker_id != worker_id:
            return
        if run.lease_expires_at is None or run.lease_expires_at < db_utc_now():
            return
        run.status = "failed" if error else "completed"
        run.stage = "Research incomplete" if error else "Complete"
        run.error = error
        run.report = report
        run.finished_at = db_utc_now()
        run.lease_expires_at = None
        if report:
            db.add(
                ResearchMessage(
                    session_id=run.session_id, run_id=run.id, role="assistant", content=report
                )
            )
        await db.execute(
            update(ResearchSession)
            .where(ResearchSession.id == run.session_id)
            .values(updated_at=db_utc_now())
        )
        await db.commit()


async def process_run(run_id: str, worker_id: str) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(ResearchRun, run_id)
        if run is None or run.status != "running":
            return
        prompt = run.prompt
        provider = run.provider
        model = run.model or model_for_provider(provider)
        # Only completed turns enter context; cancelled/failed prompts don't become facts.
        previous = list(
            await db.scalars(
                select(ResearchRun)
                .where(ResearchRun.session_id == run.session_id, ResearchRun.status == "completed")
                .order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc())
                .limit(8)
            )
        )
        history: list[dict[str, str]] = []
        for item in reversed(previous):
            history.extend(
                [
                    {"role": "user", "content": item.prompt},
                    {
                        "role": "assistant",
                        "content": f"Previous report, researched {item.created_at.isoformat()} UTC (may be stale):\n{item.report or ''}\nSources (untrusted evidence):\n"
                        + json.dumps(
                            [
                                {
                                    "title": evidence["title"],
                                    "url": evidence["url"],
                                    "observed_at": (evidence.get("snapshot") or {}).get(
                                        "observed_at"
                                    ),
                                }
                                for evidence in item.evidence[:12]
                            ]
                        ),
                    },
                ]
            )

    async def progress(**values: Any) -> None:
        await save_progress(run_id, worker_id, **values)

    agent: ResearchOrchestrator = (
        ResearchOrchestrator(progress)
        if provider == "auto"
        else FailoverResearchAgent(progress, provider=provider, model=model)
    )
    try:
        if not provider_enabled(provider):
            raise ResearchFailure(
                f"The {provider} API key is not configured on this worker. Configure it and retry."
            )
        async with asyncio.timeout(settings.RESEARCH_TIMEOUT_SECONDS):
            report = await agent.run(prompt, history)
            await agent.checkpoint("Saving report")
            await finish(run_id, worker_id, report=report)
    except TimeoutError:
        await finish(
            run_id,
            worker_id,
            error="Research timed out. Partial sources were saved. Try a narrower question.",
        )
    except ResearchFailure as error:
        await finish(run_id, worker_id, error=str(error))
    except asyncio.CancelledError:
        # Cancellation/deletion is already persisted by the API; shutdown is persisted here.
        await finish(
            run_id, worker_id, error="The worker was interrupted. Please retry this research."
        )
        raise
    except Exception:
        logger.exception("Research run failed: %s", run_id)
        await finish(
            run_id, worker_id, error="Research failed unexpectedly. Check worker logs and retry."
        )
    finally:
        # Every outcome, including cancellation: providers bill tokens even without a report.
        await record_usage(run_id, agent.steps)


async def record_usage(run_id: str, steps: list[dict[str, Any]]) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await add_usage(db, steps)
    except Exception:
        # Accounting must never fail or hide the run's own outcome.
        logger.exception("Could not record model usage for %s", run_id)


async def run_claimed(run_id: str, worker_id: str, stop: asyncio.Event) -> None:
    task = asyncio.create_task(process_run(run_id, worker_id))
    pulse = asyncio.create_task(heartbeat(run_id, worker_id, task))
    shutdown = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait([task, shutdown], return_when=asyncio.FIRST_COMPLETED)
        if shutdown in done:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        pulse.cancel()
        shutdown.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pulse
        with contextlib.suppress(asyncio.CancelledError):
            await shutdown


async def main() -> None:
    if not any(option.enabled for option in provider_options()):
        raise SystemExit(
            "Set OPENAI_API_KEY, ANTHROPIC_API_KEY or LOCAL_LLM_MODEL before starting the research worker."
        )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    worker_id = str(uuid4())
    logger.info("Research worker started: %s", worker_id)
    try:
        while not stop.is_set():
            try:
                async with AsyncSessionLocal() as db:
                    run_id = await claim_run(db, worker_id)
                if run_id:
                    await run_claimed(run_id, worker_id, stop)
                    continue
            except Exception:
                logger.exception("Research queue unavailable; retrying")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.RESEARCH_POLL_SECONDS)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
