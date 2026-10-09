"""Owner-scoped research endpoints. No provider calls run inside HTTP requests."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.time import db_utc_now
from db.dependencies import get_current_active_admin_user, get_current_active_user, get_db
from db.orm_models import User
from db.research_models import ResearchDailyUsage, ResearchMessage, ResearchRun, ResearchSession
from models.research import (
    ModelUsageReport,
    ResearchCapabilities,
    ResearchCreate,
    ResearchDetail,
    ResearchMessageOut,
    ResearchRunOut,
    ResearchSessionOut,
    ResearchSubmit,
)
from models.users import User as UserSchema
from service.research.configuration import (
    default_provider,
    model_for_provider,
    provider_enabled,
    provider_options,
)
from service.research.queue import ACTIVE, expire_runs
from service.research.usage import model_usage_totals

router = APIRouter(prefix="/research", tags=["research"])


async def owned_session(db: AsyncSession, session_id: str, user_id: int) -> ResearchSession:
    session = await db.scalar(
        select(ResearchSession).where(
            ResearchSession.id == session_id, ResearchSession.user_id == user_id
        )
    )
    if session is None:
        raise HTTPException(404, "Research session not found")
    return session


async def lock_user(db: AsyncSession, user_id: int) -> None:
    # Serialize submissions across ALL of a user's sessions, including empty queues.
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())


@router.get("/capabilities", response_model=ResearchCapabilities)
async def capabilities(user: UserSchema = Depends(get_current_active_user)):
    options = provider_options()
    enabled = any(option.enabled for option in options)
    return ResearchCapabilities(
        providers=options,
        default_provider=default_provider(),
        enabled=enabled,
        message=None
        if enabled
        else "Research needs a server-side OPENAI_API_KEY, ANTHROPIC_API_KEY or LOCAL_LLM_MODEL and a running research worker. Saved reports remain available.",
        daily_limit=settings.RESEARCH_DAILY_LIMIT,
    )


@router.get("/usage/models", response_model=ModelUsageReport)
async def model_usage(
    days: int = Query(30, ge=1, le=3660),
    admin: UserSchema = Depends(get_current_active_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-wide token totals per provider/model over the last `days` UTC days (admin only)."""
    since = (db_utc_now().date() - timedelta(days=days - 1)).isoformat()
    models = await model_usage_totals(db, since)
    input_tokens = sum(item["input_tokens"] for item in models)
    output_tokens = sum(item["output_tokens"] for item in models)
    return ModelUsageReport(
        since=since,
        models=models,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


@router.get("/sessions", response_model=list[ResearchSessionOut])
async def list_sessions(
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    return list(
        await db.scalars(
            select(ResearchSession)
            .where(ResearchSession.user_id == user.id)
            .order_by(ResearchSession.updated_at.desc(), ResearchSession.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.post("/sessions", response_model=ResearchSessionOut, status_code=201)
async def create_session(
    body: ResearchCreate,
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    session = ResearchSession(user_id=user.id, title=body.title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions/{session_id}", response_model=ResearchDetail)
async def get_session(
    session_id: str,
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    session = await owned_session(db, session_id, user.id)
    session_out = ResearchSessionOut.model_validate(session)
    await expire_runs(db)
    await db.commit()
    runs = list(
        await db.scalars(
            select(ResearchRun)
            .where(ResearchRun.session_id == session_id)
            .order_by(ResearchRun.created_at, ResearchRun.id)
        )
    )
    messages = list(
        await db.scalars(
            select(ResearchMessage)
            .where(ResearchMessage.session_id == session_id)
            .order_by(ResearchMessage.created_at, ResearchMessage.id)
        )
    )
    return ResearchDetail(
        **session_out.model_dump(),
        runs=[ResearchRunOut.model_validate(run) for run in runs],
        messages=[ResearchMessageOut.model_validate(message) for message in messages],
    )


@router.patch("/sessions/{session_id}", response_model=ResearchSessionOut)
async def rename_session(
    session_id: str,
    body: ResearchCreate,
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await lock_user(db, user.id)
    session = await owned_session(db, session_id, user.id)
    session.title = body.title
    session.updated_at = db_utc_now()
    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await lock_user(db, user.id)
    await owned_session(db, session_id, user.id)
    # Lock jobs before deletion: the worker checks this row before every persisted result.
    await db.execute(
        select(ResearchRun.id).where(ResearchRun.session_id == session_id).with_for_update()
    )
    await db.execute(delete(ResearchMessage).where(ResearchMessage.session_id == session_id))
    await db.execute(delete(ResearchRun).where(ResearchRun.session_id == session_id))
    await db.execute(delete(ResearchSession).where(ResearchSession.id == session_id))
    await db.commit()
    return Response(status_code=204)


@router.post("/sessions/{session_id}/messages", response_model=ResearchRunOut, status_code=202)
async def submit_message(
    session_id: str,
    body: ResearchSubmit,
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await lock_user(db, user.id)
    session = await owned_session(db, session_id, user.id)
    existing = await db.scalar(
        select(ResearchRun).where(
            ResearchRun.session_id == session_id, ResearchRun.request_id == str(body.request_id)
        )
    )
    if existing:
        if existing.prompt != body.prompt or (
            body.provider is not None and existing.provider != body.provider
        ):
            raise HTTPException(
                409, "This request ID was already used for a different question or provider"
            )
        return existing
    provider = body.provider or default_provider()
    if not provider_enabled(provider):
        key_name = {
            "anthropic": "ANTHROPIC_API_KEY",
            "local": "LOCAL_LLM_MODEL",
            "auto": "an API key or LOCAL_LLM_MODEL",
        }.get(provider, "OPENAI_API_KEY")
        raise HTTPException(
            503, f"Configure {key_name} on the server before starting {provider} research"
        )
    await expire_runs(db)
    active = list(
        await db.scalars(
            select(ResearchRun).where(
                ResearchRun.user_id == user.id, ResearchRun.status.in_(ACTIVE)
            )
        )
    )
    if len(active) >= settings.RESEARCH_MAX_ACTIVE_PER_USER or any(
        r.session_id == session_id for r in active
    ):
        raise HTTPException(
            409, "Research is already running. Wait for it to finish or cancel it first."
        )
    today = db_utc_now().date().isoformat()
    usage = await db.get(ResearchDailyUsage, (user.id, today))
    if usage and usage.runs >= settings.RESEARCH_DAILY_LIMIT:
        raise HTTPException(
            429, "Your daily research limit has been reached. It resets at 00:00 UTC."
        )
    if usage is None:
        usage = ResearchDailyUsage(user_id=user.id, day=today, runs=0)
        db.add(usage)
    usage.runs += 1
    run = ResearchRun(
        session_id=session_id,
        user_id=user.id,
        request_id=str(body.request_id),
        prompt=body.prompt,
        provider=provider,
        model=model_for_provider(provider),
    )
    db.add(run)
    await db.flush()
    db.add(ResearchMessage(session_id=session_id, run_id=run.id, role="user", content=body.prompt))
    session.updated_at = db_utc_now()
    if session.title == "New research":
        session.title = body.prompt[:120]
    await db.commit()
    await db.refresh(run)
    return run


@router.get("/runs/{run_id}", response_model=ResearchRunOut)
async def get_run(
    run_id: str,
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.scalar(
        select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.user_id == user.id)
    )
    if run is None:
        raise HTTPException(404, "Research run not found")
    await expire_runs(db)
    await db.commit()
    await db.refresh(run)
    return run


@router.post("/runs/{run_id}/cancel", response_model=ResearchRunOut)
async def cancel_run(
    run_id: str,
    user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.scalar(
        select(ResearchRun)
        .where(ResearchRun.id == run_id, ResearchRun.user_id == user.id)
        .with_for_update()
    )
    if run is None:
        raise HTTPException(404, "Research run not found")
    if run.status in ACTIVE:
        run.status = "cancelled"
        run.stage = "Cancelled"
        run.finished_at = db_utc_now()
        run.lease_expires_at = None
    await db.commit()
    await db.refresh(run)
    return run
