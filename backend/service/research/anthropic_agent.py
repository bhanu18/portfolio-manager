"""Claude Messages adapter using basic web search and the shared read-only tools."""

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from core.config import settings
from models.research import Citation
from service.research.agent import TOOLS, ResearchAgent, ResearchFailure, http_failure
from service.research.providers import safe_url

CLIENT_TOOLS = [
    {"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"]}
    for tool in TOOLS
    if tool["type"] == "function"
]


class AnthropicResearchAgent(ResearchAgent):
    def __init__(
        self, progress: Callable[..., Awaitable[None]], *, model: str | None = None, **options: Any
    ):
        super().__init__(progress, model=model or settings.ANTHROPIC_RESEARCH_MODEL, **options)

    async def run(self, prompt: str, history: list[dict[str, str]]) -> str:
        messages: list[dict[str, Any]] = [*history, {"role": "user", "content": prompt}]
        while (
            len(messages) > 1
            and len(json.dumps(messages, ensure_ascii=False).encode())
            > settings.RESEARCH_MAX_INPUT_TOKENS // 2
        ):
            del messages[: min(2, len(messages) - 1)]
        system = self.instructions()
        seen_calls: set[str] = set()
        report = ""
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
            for _ in range(settings.RESEARCH_MAX_MODEL_TURNS):
                remaining_tools = settings.RESEARCH_MAX_TOOL_CALLS - self.tool_calls
                remaining_output = self.output_budget - self.output_tokens
                if remaining_output < 500:
                    raise ResearchFailure(
                        "The response token budget was reached. Retry with a narrower question."
                    )
                tools = (
                    [
                        tool
                        for tool in (
                            {
                                "type": "web_search_20250305",
                                "name": "web_search",
                                "max_uses": remaining_tools,
                            },
                            *CLIENT_TOOLS,
                        )
                        if self.tool_allowed(tool["name"])
                    ]
                    if remaining_tools > 0
                    else []
                )
                bound = len(
                    json.dumps(
                        {"messages": messages, "system": system, "tools": tools}, ensure_ascii=False
                    ).encode()
                )
                if self.input_tokens + bound > settings.RESEARCH_MAX_INPUT_TOKENS:
                    raise ResearchFailure(
                        "The research context budget was reached. Try a narrower question or a new session."
                    )
                self.model_turns += 1
                await self.checkpoint("Searching sources and drafting analysis")
                try:
                    response = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": settings.ANTHROPIC_API_KEY,
                            "anthropic-version": "2023-06-01",
                        },
                        json={
                            "model": self.model,
                            "system": system,
                            "messages": messages,
                            "tools": tools,
                            "max_tokens": min(4000, remaining_output),
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPError as error:
                    raise http_failure(
                        error,
                        "Anthropic",
                        "Anthropic rejected the request. Check the model and web-search access in your Anthropic account.",
                    ) from None
                data = response.json()
                usage = data.get("usage") or {}
                self.input_tokens += (
                    sum(
                        int(usage.get(key, 0))
                        for key in (
                            "input_tokens",
                            "cache_creation_input_tokens",
                            "cache_read_input_tokens",
                        )
                    )
                    if usage
                    else bound
                )
                self.output_tokens += int(usage.get("output_tokens", min(4000, remaining_output)))
                content = data.get("content", [])
                calls = []
                search_error = False
                for block in content:
                    kind = block.get("type")
                    if kind in ("tool_use", "server_tool_use"):
                        if block["id"] not in seen_calls:
                            seen_calls.add(block["id"])
                            self.tool_calls += 1
                        if kind == "tool_use":
                            calls.append(block)
                    elif kind == "web_search_tool_result":
                        results = block.get("content", [])
                        if isinstance(results, dict):
                            search_error = True
                        else:
                            for result in results:
                                self.add_source(
                                    result.get("title") or "Web source", result.get("url", "")
                                )
                    elif kind == "text":
                        if report:
                            report += "\n\n"
                        report += block.get("text", "")
                        for citation in block.get("citations") or []:
                            url = citation.get("url", "")
                            if not safe_url(url):
                                continue
                            title = citation.get("title") or "Web source"
                            self.add_source(title, url)
                            report += " "
                            start = len(report)
                            marker = f"[Source {len(self.citations) + 1}]"
                            report += marker
                            self.citations.append(
                                Citation(
                                    url=url, title=title, start_index=start, end_index=len(report)
                                ).model_dump()
                            )
                await self.checkpoint("Verifying sources")
                if self.tool_calls > settings.RESEARCH_MAX_TOOL_CALLS:
                    raise ResearchFailure(
                        "The tool-call budget was reached. Retry with a narrower question."
                    )
                if search_error:
                    raise ResearchFailure(
                        "Anthropic web search failed or reached its search limit. Partial sources were saved; retry with a narrower question."
                    )
                stop = data.get("stop_reason")
                if stop in ("max_tokens", "refusal") or stop not in (
                    "end_turn",
                    "tool_use",
                    "pause_turn",
                ):
                    raise ResearchFailure(
                        "Anthropic returned an incomplete answer or could not answer this request. Partial sources were saved; try a narrower question."
                    )
                # Preserve server tool results, encrypted source content and citations verbatim.
                messages.append({"role": "assistant", "content": content})
                if stop == "tool_use" and calls:
                    results = []
                    for call in calls:
                        result = await self.execute_tool(
                            {"name": call["name"], "arguments": json.dumps(call.get("input", {}))}
                        )
                        results.append(
                            {"type": "tool_result", "tool_use_id": call["id"], "content": result}
                        )
                    messages.append({"role": "user", "content": results})
                    # Tool-planning narration is not the final brief.
                    report = ""
                    self.citations = []
                    continue
                if stop == "pause_turn":
                    if self.tool_calls >= settings.RESEARCH_MAX_TOOL_CALLS:
                        raise ResearchFailure(
                            "The tool-call budget was reached before Anthropic finished. Retry with a narrower question."
                        )
                    continue
                if stop != "end_turn" or calls or not report.strip():
                    raise ResearchFailure("Anthropic returned no complete report. Please retry.")
                if not self.evidence:
                    report = "No external evidence was retrieved for this response.\n\n" + report
                return report
        raise ResearchFailure(
            "The research turn limit was reached. Saved evidence is available; try a narrower question."
        )
