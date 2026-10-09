"""Per-model token accounting. Portable SQL only (no MySQL upsert) so Postgres stays possible."""

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.time import db_utc_now
from db.research_models import ResearchModelUsage

logger = logging.getLogger(__name__)
# Steps without a model call (regex rules, direct market-data tools) cost no tokens.
NON_MODEL = {"rules", "tools"}


def usage_by_model(steps: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, int]]:
    totals: dict[tuple[str, str], dict[str, int]] = {}
    for step in steps:
        if step.get("provider") in NON_MODEL or step.get("status") == "skipped":
            continue
        entry = totals.setdefault(
            (step["provider"], str(step["model"])[:100]),
            {"input_tokens": 0, "output_tokens": 0, "calls": 0, "failed_calls": 0},
        )
        entry["input_tokens"] += int(step.get("input_tokens") or 0)
        entry["output_tokens"] += int(step.get("output_tokens") or 0)
        entry["calls"] += 1
        entry["failed_calls"] += step.get("status") == "failed"
    return totals


async def add_usage(db: AsyncSession, steps: Iterable[dict[str, Any]]) -> None:
    """Add a run's per-step usage to today's per-model totals and commit."""
    totals = usage_by_model(steps)
    if not totals:
        return
    now = db_utc_now()
    day = now.date().isoformat()
    for attempt in range(2):
        try:
            # Sorted keys give concurrent workers the same lock order (no deadlocks).
            for (provider, model), values in sorted(totals.items()):
                row = await db.scalar(
                    select(ResearchModelUsage)
                    .where(
                        ResearchModelUsage.day == day,
                        ResearchModelUsage.provider == provider,
                        ResearchModelUsage.model == model,
                    )
                    .with_for_update()
                )
                if row is None:
                    row = ResearchModelUsage(
                        day=day,
                        provider=provider,
                        model=model,
                        input_tokens=0,
                        output_tokens=0,
                        calls=0,
                        failed_calls=0,
                    )
                    db.add(row)
                for key, value in values.items():
                    setattr(row, key, getattr(row, key) + value)
                row.updated_at = now
            await db.commit()
            return
        except IntegrityError:
            # Another worker inserted the same new row first; retry as an update.
            await db.rollback()
            if attempt:
                raise


async def model_usage_totals(db: AsyncSession, since: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            ResearchModelUsage.provider,
            ResearchModelUsage.model,
            func.sum(ResearchModelUsage.input_tokens),
            func.sum(ResearchModelUsage.output_tokens),
            func.sum(ResearchModelUsage.calls),
            func.sum(ResearchModelUsage.failed_calls),
        )
        .where(ResearchModelUsage.day >= since)
        .group_by(ResearchModelUsage.provider, ResearchModelUsage.model)
    )
    totals = [
        {
            "provider": provider,
            "model": model,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(input_tokens or 0) + int(output_tokens or 0),
            "calls": int(calls or 0),
            "failed_calls": int(failed or 0),
        }
        for provider, model, input_tokens, output_tokens, calls, failed in rows.all()
    ]
    return sorted(totals, key=lambda item: item["total_tokens"], reverse=True)
