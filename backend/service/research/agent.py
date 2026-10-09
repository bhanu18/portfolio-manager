"""Bounded Responses API agent. Only explicit read-only tools are executable."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.config import settings
from models.research import Citation, Evidence
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


class ResearchFailure(Exception):
    """Safe, actionable error that may be shown to a user."""


class ResearchAgent:
    def __init__(self, progress: Callable[..., Awaitable[None]], *, model: str | None = None):
        self.model = model or settings.RESEARCH_MODEL
        self.progress = progress
        self.evidence: list[dict[str, Any]] = []
        self.citations: list[dict[str, Any]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.tool_calls = 0
        self.model_turns = 0

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

    async def execute_tool(self, item: dict[str, Any]) -> str:
        name = item.get("name")
        await self.checkpoint(
            "Reading Treasury rates"
            if name == "treasury_snapshot"
            else "Calculating moving averages and backtests"
            if name == "investment_analysis"
            else "Reading stock and ETF data"
        )
        try:
            args = json.loads(item.get("arguments", "{}"))
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
            entry = Evidence(
                title=snapshot.symbol or f"US Treasury {snapshot.kind}",
                url=snapshot.source_url,
                retrieved_at=snapshot.retrieved_at,
                snapshot=snapshot,
            )
            self.evidence.append(entry.model_dump())
            await self.checkpoint("Checking market evidence")
            # Persist full chart data, but keep model context bounded to numeric summaries.
            payload = snapshot.model_dump()
            if payload.get("analysis"):
                payload["analysis"].pop("trend", None)
                for result in payload["analysis"]["backtests"]:
                    result.pop("curve", None)
            return json.dumps(payload)
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
        # A byte count is a conservative token upper bound (including non-ASCII text).
        # History is trimmed by whole turns, keeping the current question intact.
        inputs: list[dict[str, Any]] = [*history, {"role": "user", "content": prompt}]
        while (
            len(inputs) > 1
            and len(json.dumps(inputs, ensure_ascii=False).encode())
            > settings.RESEARCH_MAX_INPUT_TOKENS // 2
        ):
            del inputs[: min(2, len(inputs) - 1)]
        instructions = SYSTEM + f"\nToday's UTC date: {datetime.now(UTC).date().isoformat()}."
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
            for _ in range(settings.RESEARCH_MAX_MODEL_TURNS):
                remaining_tools = settings.RESEARCH_MAX_TOOL_CALLS - self.tool_calls
                remaining_output = settings.RESEARCH_MAX_OUTPUT_TOKENS - self.output_tokens
                if remaining_output < 500:
                    raise ResearchFailure(
                        "The response token budget was reached. Retry with a narrower question."
                    )
                tools = TOOLS if remaining_tools > 0 else []
                bound = len(
                    json.dumps(
                        {"input": inputs, "instructions": instructions, "tools": tools},
                        ensure_ascii=False,
                    ).encode()
                )
                if self.input_tokens + bound > settings.RESEARCH_MAX_INPUT_TOKENS:
                    raise ResearchFailure(
                        "The research context budget was reached. Try a narrower question or a new session."
                    )
                self.model_turns += 1
                await self.checkpoint("Searching sources and drafting analysis")
                payload: dict[str, Any] = {
                    "model": self.model,
                    "instructions": instructions,
                    "input": inputs,
                    "tools": tools,
                    "store": False,
                    "include": ["web_search_call.action.sources", "reasoning.encrypted_content"],
                    "max_output_tokens": min(4000, remaining_output),
                }
                if remaining_tools:
                    payload["max_tool_calls"] = remaining_tools
                try:
                    response = await client.post(
                        "https://api.openai.com/v1/responses",
                        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                        json=payload,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    if error.response.status_code in (401, 403):
                        raise ResearchFailure(
                            "The research API key or model access needs attention on the server."
                        ) from None
                    if error.response.status_code == 429:
                        raise ResearchFailure(
                            "The AI provider's rate or billing limit was reached. Check API billing and retry later."
                        ) from None
                    raise ResearchFailure(
                        "The AI provider rejected the request. Check model configuration and retry."
                    ) from None
                except httpx.HTTPError:
                    raise ResearchFailure(
                        "The AI provider could not be reached. Please retry later."
                    ) from None
                data = response.json()
                usage = data.get("usage") or {}
                self.input_tokens += int(usage.get("input_tokens", bound))
                self.output_tokens += int(usage.get("output_tokens", min(4000, remaining_output)))
                outputs = data.get("output", [])
                calls = []
                text_parts: list[str] = []
                self.citations = []
                for item in outputs:
                    item_type = item.get("type")
                    if item_type in ("web_search_call", "function_call"):
                        self.tool_calls += 1
                    if item_type == "web_search_call":
                        for source in (item.get("action") or {}).get("sources", []):
                            self.add_source(
                                source.get("title") or source.get("url", "Source"),
                                source.get("url", ""),
                            )
                    elif item_type == "function_call":
                        calls.append(item)
                    elif item_type == "message":
                        for content in item.get("content", []):
                            if content.get("type") == "refusal":
                                raise ResearchFailure(
                                    "The research provider could not answer this request. Rephrase the question."
                                )
                            if content.get("type") != "output_text":
                                continue
                            offset = sum(len(part) + 2 for part in text_parts)
                            value = content.get("text", "")
                            text_parts.append(value)
                            for annotation in content.get("annotations", []):
                                if annotation.get("type") == "url_citation" and safe_url(
                                    annotation.get("url", "")
                                ):
                                    start, end = (
                                        annotation.get("start_index"),
                                        annotation.get("end_index"),
                                    )
                                    valid_span = (
                                        isinstance(start, int)
                                        and isinstance(end, int)
                                        and 0 <= start < end <= len(value)
                                    )
                                    self.citations.append(
                                        Citation(
                                            url=annotation["url"],
                                            title=annotation.get("title") or "Source",
                                            start_index=start + offset if valid_span else None,
                                            end_index=end + offset if valid_span else None,
                                        ).model_dump()
                                    )
                                    self.add_source(
                                        annotation.get("title") or "Source", annotation["url"]
                                    )
                await self.checkpoint("Verifying sources")
                if self.tool_calls > settings.RESEARCH_MAX_TOOL_CALLS:
                    raise ResearchFailure(
                        "The tool-call budget was reached. Retry with a narrower question."
                    )
                if data.get("status") != "completed":
                    raise ResearchFailure(
                        "The provider returned an incomplete answer. Saved evidence is available; retry with a narrower question."
                    )
                inputs.extend(outputs)
                if calls:
                    for call in calls:
                        result = await self.execute_tool(call)
                        inputs.append(
                            {
                                "type": "function_call_output",
                                "call_id": call["call_id"],
                                "output": result,
                            }
                        )
                    continue
                report = "\n\n".join(text_parts)
                if not report.strip():
                    raise ResearchFailure("The provider returned no report. Please retry.")
                if not self.evidence:
                    # Clarifying questions can be unsourced; do not present them as verified research.
                    report = "No external evidence was retrieved for this response.\n\n" + report
                    for citation in self.citations:
                        if citation["start_index"] is not None:
                            citation["start_index"] += len(
                                "No external evidence was retrieved for this response.\n\n"
                            )
                            citation["end_index"] += len(
                                "No external evidence was retrieved for this response.\n\n"
                            )
                return report
        raise ResearchFailure(
            "The research turn limit was reached. Saved evidence is available; try a narrower question."
        )
