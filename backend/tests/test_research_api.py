"""Research API isolation, durable queue and usage-budget integration tests."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.config import settings
from db.orm_models import User
from db.research_models import ResearchDailyUsage, ResearchRun


@pytest.fixture
async def research_user(client, db_session, monkeypatch):
    from db.dependencies import get_current_active_user
    from main import app

    user = User(
        name="researcher",
        email="researcher@example.com",
        hashed_password="unused",
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    app.dependency_overrides[get_current_active_user] = lambda: user
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "RESEARCH_PROVIDER", "openai")
    return user


async def create(client):
    response = await client.post("/research/sessions", json={})
    assert response.status_code == 201
    return response.json()["id"]


async def submit(client, session_id, prompt="Research Apple", request_id=None):
    return await client.post(
        f"/research/sessions/{session_id}/messages",
        json={"prompt": prompt, "request_id": request_id or str(uuid4())},
    )


async def test_research_requires_auth(client):
    assert (await client.get("/research/sessions")).status_code == 401


async def test_session_lifecycle_and_idempotency(client, db_session, research_user):
    session = await create(client)
    key = str(uuid4())
    first = await submit(client, session, request_id=key)
    assert first.status_code == 202
    run_id = first.json()["id"]
    assert first.json()["status"] == "queued"
    assert first.json()["created_at"].endswith("+00:00")
    second = await submit(client, session, request_id=key)
    assert second.json()["id"] == run_id
    assert (await submit(client, session, prompt="Different", request_id=key)).status_code == 409
    assert (await submit(client, session)).status_code == 409
    other = await create(client)
    assert (await submit(client, other)).status_code == 409
    detail = (await client.get(f"/research/sessions/{session}")).json()
    assert detail["title"] == "Research Apple" and len(detail["messages"]) == 1
    assert len((await client.get("/research/sessions")).json()) == 2
    assert (await client.patch(f"/research/sessions/{session}", json={"title": "My brief"})).json()[
        "title"
    ] == "My brief"
    assert (await client.post(f"/research/runs/{run_id}/cancel")).json()["status"] == "cancelled"
    assert (await client.post(f"/research/runs/{run_id}/cancel")).json()["status"] == "cancelled"
    assert (await submit(client, session)).status_code == 202
    assert (await client.delete(f"/research/sessions/{session}")).status_code == 204
    assert (await client.get(f"/research/runs/{run_id}")).status_code == 404


async def test_owner_isolation_every_path(client, db_session, research_user):
    from db.dependencies import get_current_active_user
    from main import app

    session = await create(client)
    run_id = (await submit(client, session)).json()["id"]
    other = User(
        name="otherresearcher",
        email="otherresearcher@example.com",
        hashed_password="unused",
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    app.dependency_overrides[get_current_active_user] = lambda: other
    assert (await client.get("/research/sessions")).json() == []
    for method, path, body in [
        ("get", f"/research/sessions/{session}", None),
        ("patch", f"/research/sessions/{session}", {"title": "Stolen"}),
        ("delete", f"/research/sessions/{session}", None),
        (
            "post",
            f"/research/sessions/{session}/messages",
            {"prompt": "Read", "request_id": str(uuid4())},
        ),
        ("get", f"/research/runs/{run_id}", None),
        ("post", f"/research/runs/{run_id}/cancel", None),
    ]:
        response = await client.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 404


async def test_missing_credentials_preserves_history(client, research_user, monkeypatch):
    session = await create(client)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert (await client.get("/research/capabilities")).json()["enabled"] is False
    assert (await submit(client, session)).status_code == 503
    assert (await client.get(f"/research/sessions/{session}")).status_code == 200


async def test_daily_limit_survives_deletion(client, db_session, research_user, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_DAILY_LIMIT", 1)
    session = await create(client)
    assert (await submit(client, session)).status_code == 202
    await client.delete(f"/research/sessions/{session}")
    next_session = await create(client)
    assert (await submit(client, next_session)).status_code == 429
    usage = await db_session.scalar(select(ResearchDailyUsage))
    assert usage.runs == 1


async def test_queue_claim_expiry_and_cancellation(client, db_session, research_user):
    from service.research.queue import claim_run, expire_runs

    session = await create(client)
    run_id = (await submit(client, session)).json()["id"]
    assert await claim_run(db_session, "worker-a") == run_id
    assert await claim_run(db_session, "worker-b") is None
    run = await db_session.get(ResearchRun, run_id)
    assert run.worker_id == "worker-a"
    run.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    run.evidence = [
        {
            "title": "Preserved",
            "url": "https://www.sec.gov",
            "retrieved_at": datetime.utcnow().isoformat(),
            "snapshot": None,
        }
    ]
    await db_session.commit()
    await expire_runs(db_session)
    await db_session.commit()
    response = (await client.get(f"/research/runs/{run_id}")).json()
    assert response["status"] == "failed" and response["evidence"][0]["title"] == "Preserved"
    retry = await submit(client, session)
    assert retry.status_code == 202
    await client.post(f"/research/runs/{retry.json()['id']}/cancel")
    assert await claim_run(db_session, "worker-b") is None


async def test_queued_job_without_worker_expires(client, db_session, research_user):
    session = await create(client)
    run_id = (await submit(client, session)).json()["id"]
    run = await db_session.get(ResearchRun, run_id)
    run.created_at = datetime.utcnow() - timedelta(seconds=settings.RESEARCH_TIMEOUT_SECONDS + 1)
    await db_session.commit()
    response = (await client.get(f"/research/runs/{run_id}")).json()
    assert response["status"] == "failed"
    assert "worker" in response["error"]


@pytest.fixture
async def worker_db(db_session, monkeypatch):
    from contextlib import asynccontextmanager

    from service.research import worker

    @asynccontextmanager
    async def factory():
        yield db_session

    monkeypatch.setattr(worker, "AsyncSessionLocal", factory)
    return worker


async def test_worker_completion_persists_report_and_followups(
    client, db_session, research_user, worker_db, monkeypatch
):
    from service.research.queue import claim_run

    session = await create(client)
    run_id = (await submit(client, session)).json()["id"]
    await claim_run(db_session, "worker-test")
    calls = []

    async def fake_agent(self, prompt, history):
        calls.append((prompt, history))
        self.evidence = [
            {
                "title": "Issuer",
                "url": "https://www.apple.com",
                "retrieved_at": "2026-10-08T00:00:00+00:00",
                "snapshot": None,
            }
        ]
        self.input_tokens = 100
        self.output_tokens = 50
        await self.checkpoint("Reading issuer sources")
        return "## Summary\nA report with [issuer evidence](https://www.apple.com)."

    monkeypatch.setattr(worker_db.ResearchAgent, "run", fake_agent)
    await worker_db.process_run(run_id, "worker-test")
    detail = (await client.get(f"/research/sessions/{session}")).json()
    assert detail["runs"][0]["status"] == "completed"
    assert detail["messages"][1]["role"] == "assistant"
    assert detail["runs"][0]["input_tokens"] == 100
    next_run = (await submit(client, session, prompt="What are the risks?")).json()["id"]
    await claim_run(db_session, "worker-test")
    await worker_db.process_run(next_run, "worker-test")
    assert calls[1][1][0]["content"] == "Research Apple"
    assert "Previous report" in calls[1][1][1]["content"]


async def test_worker_cannot_complete_cancelled_or_expired_job(
    client, db_session, research_user, worker_db
):
    import asyncio

    from service.research.queue import claim_run

    session = await create(client)
    run_id = (await submit(client, session)).json()["id"]
    await claim_run(db_session, "worker-test")
    await client.post(f"/research/runs/{run_id}/cancel")
    with pytest.raises(asyncio.CancelledError):
        await worker_db.save_progress(run_id, "worker-test", stage="Late update")
    await worker_db.finish(run_id, "worker-test", report="Late report")
    assert (await client.get(f"/research/runs/{run_id}")).json()["report"] is None
    retry_id = (await submit(client, session)).json()["id"]
    await claim_run(db_session, "worker-test")
    run = await db_session.get(ResearchRun, retry_id)
    run.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(asyncio.CancelledError):
        await worker_db.save_progress(retry_id, "worker-test", stage="Expired update")
    await worker_db.finish(retry_id, "worker-test", report="Expired report")
    response = (await client.get(f"/research/runs/{retry_id}")).json()
    assert response["status"] == "failed" and response["report"] is None


async def test_worker_failure_keeps_evidence(
    client, db_session, research_user, worker_db, monkeypatch
):
    from service.research.agent import ResearchFailure
    from service.research.queue import claim_run

    session = await create(client)
    run_id = (await submit(client, session)).json()["id"]
    await claim_run(db_session, "worker-test")

    async def fail_agent(self, prompt, history):
        self.evidence = [
            {
                "title": "SEC",
                "url": "https://www.sec.gov",
                "retrieved_at": "2026-10-08T00:00:00+00:00",
                "snapshot": None,
            }
        ]
        await self.checkpoint("Reading filings")
        raise ResearchFailure("Provider temporarily unavailable")

    monkeypatch.setattr(worker_db.ResearchAgent, "run", fail_agent)
    await worker_db.process_run(run_id, "worker-test")
    response = (await client.get(f"/research/runs/{run_id}")).json()
    assert response["status"] == "failed"
    assert response["evidence"][0]["title"] == "SEC"
    assert response["report"] is None


async def test_concurrent_submissions_and_worker_claims(migrate_test_db, monkeypatch):
    """Use independent real transactions to exercise the owner lock and SKIP LOCKED."""
    import asyncio

    from fastapi import HTTPException
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from db.research_models import ResearchMessage, ResearchSession
    from models.research import ResearchSubmit
    from routers.research import submit_message
    from service.research.queue import claim_run

    engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "RESEARCH_PROVIDER", "openai")
    async with factory() as db:
        user = User(
            name="concurrent-research",
            email="concurrent@example.com",
            hashed_password="unused",
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(user)
        await db.flush()
        user_id = user.id
        sessions = [ResearchSession(user_id=user_id), ResearchSession(user_id=user_id)]
        db.add_all(sessions)
        await db.commit()
        ids = [session.id for session in sessions]

    async def submit_one(session_id):
        async with factory() as db:
            try:
                result = await submit_message(
                    session_id,
                    ResearchSubmit(prompt="Research Apple", request_id=uuid4()),
                    user,
                    db,
                )
                return result.id
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    async def claim_one(worker_id):
        async with factory() as db:
            return await claim_run(db, worker_id)

    try:
        results = await asyncio.gather(*(submit_one(session_id) for session_id in ids))
        assert results.count(409) == 1
        run_ids = [result for result in results if isinstance(result, str)]
        assert len(run_ids) == 1
        claims = await asyncio.gather(claim_one("first-worker"), claim_one("second-worker"))
        assert claims.count(run_ids[0]) == 1 and claims.count(None) == 1
    finally:
        async with factory() as db:
            await db.execute(delete(ResearchMessage).where(ResearchMessage.session_id.in_(ids)))
            await db.execute(delete(ResearchRun).where(ResearchRun.user_id == user_id))
            await db.execute(delete(ResearchSession).where(ResearchSession.user_id == user_id))
            await db.execute(
                delete(ResearchDailyUsage).where(ResearchDailyUsage.user_id == user_id)
            )
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()


def test_research_migration_round_trip(migrate_test_db):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from tests.conftest import BACKEND_DIR, TEST_SYNC_URL

    config = Config(f"{BACKEND_DIR}/alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_SYNC_URL)
    engine = create_engine(TEST_SYNC_URL)
    try:
        command.downgrade(config, "2f8ad6c1b503")
        assert "research_runs" not in inspect(engine).get_table_names()
        assert "users" in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        tables = inspect(engine).get_table_names()
        assert {
            "research_sessions",
            "research_runs",
            "research_messages",
            "research_daily_usage",
        }.issubset(tables)
        columns = {
            column["name"]: column for column in inspect(engine).get_columns("research_messages")
        }
        assert columns["created_at"]["type"].fsp == 6
    finally:
        engine.dispose()


async def test_anthropic_selection_and_configuration(client, research_user, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    session = await create(client)
    payload = {"prompt": "Research Apple", "request_id": str(uuid4()), "provider": "anthropic"}
    assert (
        await client.post(f"/research/sessions/{session}/messages", json=payload)
    ).status_code == 503
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    caps = (await client.get("/research/capabilities")).json()
    assert caps["enabled"] and caps["default_provider"] == "anthropic"
    assert len(caps["providers"]) == 2
    response = await client.post(f"/research/sessions/{session}/messages", json=payload)
    assert response.status_code == 202
    assert response.json()["provider"] == "anthropic"
    assert response.json()["model"] == settings.ANTHROPIC_RESEARCH_MODEL
    payload["provider"] = "openai"
    assert (
        await client.post(f"/research/sessions/{session}/messages", json=payload)
    ).status_code == 409
    payload["provider"] = "unknown"
    assert (
        await client.post(f"/research/sessions/{session}/messages", json=payload)
    ).status_code == 422


async def test_worker_uses_saved_anthropic_model(
    client, db_session, research_user, worker_db, monkeypatch
):
    from service.research.queue import claim_run

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(settings, "ANTHROPIC_RESEARCH_MODEL", "saved-model")
    session = await create(client)
    response = await client.post(
        f"/research/sessions/{session}/messages",
        json={"prompt": "Research Apple", "request_id": str(uuid4()), "provider": "anthropic"},
    )
    run_id = response.json()["id"]
    await claim_run(db_session, "claude-worker")
    monkeypatch.setattr(settings, "ANTHROPIC_RESEARCH_MODEL", "changed-model")

    async def fake_agent(self, prompt, history):
        assert self.model == "saved-model"
        return "Claude report"

    monkeypatch.setattr(worker_db.AnthropicResearchAgent, "run", fake_agent)
    await worker_db.process_run(run_id, "claude-worker")
    result = (await client.get(f"/research/runs/{run_id}")).json()
    assert result["status"] == "completed"
    assert result["report"] == "Claude report"
    assert result["model"] == "saved-model"
