"""Shared research-agent state: budgets, evidence, citations, progress and the read-only market
tools. Provider loops live in `langchain_agent.py`; only explicit read-only tools are executable."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.config import settings
from models.research import Evidence, MarketSnapshot
from service.research.errors import (  # noqa: F401  (re-exported for existing imports)
    ProviderUnavailable,
    ResearchFailure,
)
from service.research.investment import investment_snapshot
from service.research.providers import safe_url, stock_snapshot, treasury_snapshot

SYSTEM = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")

TOOLS: list[dict[str, Any]] = [
    {"type": "web_search"},
    {
        "type": "function",
        "name": "stock_snapshot",
        "description": "Read a public stock/ETF price and fundamentals snapshot by US ticker.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "investment_analysis",
        "description": "Calculate MA50/200 and three fixed next-session backtests for a stock/ETF using up to ten years of daily adjusted history. Returns deterministic metrics and assumptions.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "treasury_snapshot",
        "description": "Read the latest official US Treasury par yield curve or Treasury bill rates.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["curve", "bills"]}},
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
]


class ResearchAgent:
    def __init__(
        self,
        progress: Callable[..., Awaitable[None]],
        *,
        model: str | None = None,
        allowed_tools: set[str] | None = None,
        extra_instructions: str = "",
        max_output_tokens: int | None = None,
    ):
        self.model = model or settings.RESEARCH_MODEL
        self.progress = progress
        # None means every tool; the orchestrator narrows tools and budgets per step.
        self.allowed_tools = allowed_tools
        self.extra_instructions = extra_instructions
        self.output_budget = min(
            max_output_tokens or settings.RESEARCH_MAX_OUTPUT_TOKENS,
            settings.RESEARCH_MAX_OUTPUT_TOKENS,
        )
        self.evidence: list[dict[str, Any]] = []
        self.citations: list[dict[str, Any]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.tool_calls = 0
        self.model_turns = 0

    def tool_allowed(self, name: str) -> bool:
        return self.allowed_tools is None or name in self.allowed_tools

    def instructions(self) -> str:
        text = SYSTEM + f"\nToday's UTC date: {datetime.now(UTC).date().isoformat()}."
        return f"{text}\n\n{self.extra_instructions}" if self.extra_instructions else text

    def record_snapshot(self, snapshot: MarketSnapshot) -> str:
        """Save a snapshot as evidence and return its bounded model-context JSON."""
        entry = Evidence(
            title=snapshot.symbol or f"US Treasury {snapshot.kind}",
            url=snapshot.source_url,
            retrieved_at=snapshot.retrieved_at,
            snapshot=snapshot,
        )
        self.evidence.append(entry.model_dump())
        # Persist full chart data, but keep model context bounded to numeric summaries.
        payload = snapshot.model_dump()
        if payload.get("analysis"):
            payload["analysis"].pop("trend", None)
            for result in payload["analysis"]["backtests"]:
                result.pop("curve", None)
        return json.dumps(payload)

    async def checkpoint(self, stage: str) -> None:
        await self.progress(
            stage=stage,
            evidence=self.evidence,
            citations=self.citations,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            tool_calls=self.tool_calls,
            model_turns=self.model_turns,
            model=self.model,
        )

    def add_source(self, title: str, url: str) -> None:
        if safe_url(url) and not any(item["url"] == url for item in self.evidence):
            self.evidence.append(
                Evidence(
                    title=title[:300], url=url, retrieved_at=datetime.now(UTC).isoformat()
                ).model_dump()
            )

    async def market_tool(self, name: str, args: Any) -> str:
        """Run one read-only market tool (called by the LangChain tools in `tools.py`).

        Always returns model-context JSON; failures become safe error messages, never raise.
        """
        await self.checkpoint(
            "Reading Treasury rates"
            if name == "treasury_snapshot"
            else "Calculating moving averages and backtests"
            if name == "investment_analysis"
            else "Reading stock and ETF data"
        )
        if not name or not self.tool_allowed(name):
            return json.dumps({"error": "Unsupported read-only tool or arguments"})
        try:
            if not isinstance(args, dict):
                raise ValueError("Invalid tool arguments")
            if (
                name in ("stock_snapshot", "investment_analysis")
                and set(args) == {"symbol"}
                and isinstance(args["symbol"], str)
            ):
                snapshot = await (
                    investment_snapshot(args["symbol"])
                    if name == "investment_analysis"
                    else stock_snapshot(args["symbol"])
                )
            elif name == "treasury_snapshot" and set(args) == {"kind"}:
                snapshot = await treasury_snapshot(args["kind"])
            else:
                return json.dumps({"error": "Unsupported read-only tool or arguments"})
            result = self.record_snapshot(snapshot)
            await self.checkpoint("Checking market evidence")
            return result
        except (httpx.HTTPError, ValueError, TypeError, TimeoutError, KeyError):
            if name == "investment_analysis":
                return json.dumps(
                    {
                        "error": "Moving averages and backtests unavailable: historical prices could not be validated. At least 201 completed daily observations are required. Do not invent results."
                    }
                )
            return json.dumps(
                {
                    "error": "Market provider unavailable or instrument not found. State missing data explicitly; do not infer a quote."
                }
            )
        except Exception:
            # Yahoo can raise provider-specific exceptions; never expose upstream payloads.
            return json.dumps({"error": "Market provider failed. This data is unavailable."})

    async def run(self, prompt: str, history: list[dict[str, str]]) -> str:
        """Answer one research turn; provider agents implement this (see langchain_agent.py)."""
        raise NotImplementedError
