"""Private research history and durable worker queue. All stored dates are UTC."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from core.time import db_utc_now
from db.orm_models import Base

# Preserve ordering of fast consecutive messages on MySQL (default DATETIME drops microseconds).
RESEARCH_TIMESTAMP = DateTime().with_variant(DATETIME(fsp=6), "mysql")


def new_id() -> str:
    return str(uuid4())


class ResearchSession(Base):
    __tablename__ = "research_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New research")
    created_at: Mapped[datetime] = mapped_column(RESEARCH_TIMESTAMP, default=db_utc_now)
    updated_at: Mapped[datetime] = mapped_column(RESEARCH_TIMESTAMP, default=db_utc_now)


class ResearchRun(Base):
    __tablename__ = "research_runs"
    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_research_request"),
        Index("ix_research_queue", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("research_sessions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20), default="openai", server_default="openai")
    request_id: Mapped[str] = mapped_column(String(36))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str] = mapped_column(String(160), default="Waiting for research worker")
    report: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    model_turns: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Per-step model routing and usage for Auto runs; NULL for single-provider runs.
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(RESEARCH_TIMESTAMP, nullable=True)
    created_at: Mapped[datetime] = mapped_column(RESEARCH_TIMESTAMP, default=db_utc_now)
    started_at: Mapped[datetime | None] = mapped_column(RESEARCH_TIMESTAMP, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(RESEARCH_TIMESTAMP, nullable=True)


class ResearchMessage(Base):
    __tablename__ = "research_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("research_sessions.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(RESEARCH_TIMESTAMP, default=db_utc_now)


class ResearchDailyUsage(Base):
    """Retained across session deletion so limits cannot be bypassed."""

    __tablename__ = "research_daily_usage"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)


class ResearchModelUsage(Base):
    """Tokens spent per model per UTC day, across all users and runs.

    Includes failed, cancelled and failed-over calls: tokens a provider billed are counted
    even when no report was saved. Retained when sessions are deleted.
    """

    __tablename__ = "research_model_usage"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(RESEARCH_TIMESTAMP, default=db_utc_now)
