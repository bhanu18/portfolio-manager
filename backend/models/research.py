"""API contracts; UTC timestamps are serialized with an explicit timezone."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

ResearchProviderId = Literal["openai", "anthropic", "local", "auto"]


class ResearchCreate(BaseModel):
    title: str = Field(default="New research", min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value.strip()


class ResearchSubmit(BaseModel):
    prompt: str = Field(min_length=1, max_length=6000)
    request_id: UUID
    provider: ResearchProviderId | None = None

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a research question")
        return value.strip()


class ResearchRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at", "started_at", "finished_at", check_fields=False)
    def utc_date(self, value: datetime | None) -> str | None:
        return value.replace(tzinfo=UTC).isoformat() if value else None


class ResearchSessionOut(ResearchRecord):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class Citation(BaseModel):
    url: str
    title: str
    start_index: int | None = None
    end_index: int | None = None


class TrendPoint(BaseModel):
    date: str
    price: float
    sma50: float | None
    sma200: float | None


class BacktestCurvePoint(BaseModel):
    date: str
    equity: float
    drawdown: float


class BacktestResult(BaseModel):
    strategy: str
    period: str
    start: str
    end: str
    total_return: float
    annualized_return: float | None
    max_drawdown: float
    annualized_volatility: float | None
    trades: int
    time_invested: float
    curve: list[BacktestCurvePoint]


class InvestmentAnalysis(BaseModel):
    price: float
    sma50: float
    sma200: float
    distance_sma50: float
    distance_sma200: float
    sma50_change_20_sessions: float | None
    sma200_change_20_sessions: float | None
    last_crossover: dict[str, str] | None
    trend: list[TrendPoint]
    backtests: list[BacktestResult]
    assumptions: list[str]


class MarketSnapshot(BaseModel):
    kind: str
    analysis: InvestmentAnalysis | None = None
    symbol: str | None = None
    observed_at: str | None = None
    retrieved_at: str
    source_url: str
    values: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    definitions: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    title: str
    url: str
    retrieved_at: str
    snapshot: MarketSnapshot | None = None


class ResearchStep(BaseModel):
    """One orchestrated sub-task and the model that handled it (Auto runs only)."""

    role: Literal["classify", "data", "web", "writer"]
    provider: Literal["openai", "anthropic", "local", "rules", "tools"]
    model: str
    status: Literal["running", "completed", "failed", "skipped"]
    input_tokens: int = 0
    output_tokens: int = 0
    note: str | None = None


class ResearchRunOut(ResearchRecord):
    id: str
    session_id: str
    provider: ResearchProviderId
    prompt: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: str
    report: str | None
    error: str | None
    evidence: list[Evidence]
    citations: list[Citation]
    input_tokens: int
    output_tokens: int
    tool_calls: int
    model_turns: int
    model: str | None
    steps: list[ResearchStep] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @field_validator("steps", mode="before")
    @classmethod
    def no_steps(cls, value: Any) -> Any:
        # Runs created before orchestration have a NULL steps column.
        return value or []


class ResearchMessageOut(ResearchRecord):
    id: str
    run_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ResearchDetail(ResearchSessionOut):
    runs: list[ResearchRunOut]
    messages: list[ResearchMessageOut]


class ResearchProviderOption(BaseModel):
    id: ResearchProviderId
    label: str
    model: str
    enabled: bool


class ResearchCapabilities(BaseModel):
    providers: list[ResearchProviderOption]
    default_provider: str
    enabled: bool
    message: str | None
    daily_limit: int
    max_prompt_chars: int = 6000


class ModelUsageOut(BaseModel):
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    calls: int
    failed_calls: int


class ModelUsageReport(BaseModel):
    since: str
    models: list[ModelUsageOut]
    input_tokens: int
    output_tokens: int
    total_tokens: int
