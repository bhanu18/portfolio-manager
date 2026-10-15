"""Research agents on LangChain: `create_agent` plus middleware that keeps the research rules.

`BudgetMiddleware` reproduces the httpx loops' behaviour: token, context and tool-call budgets
(web searches included), per-call output caps, progress stages, source collection, stop-reason
checks, and Anthropic `pause_turn` continuation. Provider errors become the same
`ProviderUnavailable`/`ResearchFailure` the orchestrator fails over on.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware, hook_config
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.types import Command

from core.config import settings
from models.research import Citation
from service.research.agent import ResearchAgent
from service.research.errors import ResearchFailure, provider_failure
from service.research.models import chat_model
from service.research.providers import safe_url
from service.research.tools import make_tools, web_search_tool

UNSUPPORTED = json.dumps({"error": "Unsupported read-only tool or arguments"})
NO_EVIDENCE = "No external evidence was retrieved for this response.\n\n"
# LangGraph counts every node (middleware hooks included); the turn limit is enforced separately.
RECURSION_LIMIT = 100


class BudgetMiddleware(AgentMiddleware):
    """Budgets, progress and stop-reason rules around every model and tool call."""

    def __init__(self, agent: "LangChainResearchAgent"):
        super().__init__()
        self.agent = agent
        self.seen_calls: set[str] = set()

    def call_tools(self, request: ModelRequest, remaining: int) -> list[Any]:
        """Market tools plus provider web search, capped to the remaining tool budget."""
        if remaining <= 0:
            return []
        tools: list[Any] = [tool for tool in request.tools if not isinstance(tool, dict)]
        search = web_search_tool(self.agent.provider, remaining)
        if search and self.agent.tool_allowed("web_search"):
            tools.insert(0, search)
        return tools

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        agent = self.agent
        remaining_tools = settings.RESEARCH_MAX_TOOL_CALLS - agent.tool_calls
        remaining_output = agent.output_budget - agent.output_tokens
        if remaining_output < 500:
            raise ResearchFailure(
                "The response token budget was reached. Retry with a narrower question."
            )
        tools = self.call_tools(request, remaining_tools)
        # A byte count is a conservative token upper bound, as in the httpx adapters.
        bound = len(
            json.dumps(
                {
                    "messages": [message.content for message in request.messages],
                    "system": agent.instructions(),
                    "tools": [
                        t if isinstance(t, dict) else convert_to_openai_tool(t) for t in tools
                    ],
                },
                ensure_ascii=False,
                default=str,
            ).encode()
        )
        if agent.input_tokens + bound > settings.RESEARCH_MAX_INPUT_TOKENS:
            raise ResearchFailure(
                "The research context budget was reached. Try a narrower question or a new session."
            )
        agent.model_turns += 1
        await agent.checkpoint("Searching sources and drafting analysis")
        cap = min(4000, remaining_output)
        response = await handler(
            request.override(
                tools=tools, model_settings={**request.model_settings, "max_tokens": cap}
            )
        )
        message = next(m for m in reversed(response.result) if isinstance(m, AIMessage))
        await self.account(message, bound, cap)
        return response

    async def account(self, message: AIMessage, bound: int, cap: int) -> None:
        agent = self.agent
        usage = message.usage_metadata
        agent.input_tokens += int(usage["input_tokens"]) if usage else bound
        agent.output_tokens += int(usage["output_tokens"]) if usage else cap
        search_failed = False
        for block in message.content_blocks:
            kind = block.get("type")
            if kind in ("server_tool_call", "tool_call"):
                call_id = str(block.get("id"))
                if call_id not in self.seen_calls:
                    self.seen_calls.add(call_id)
                    agent.tool_calls += 1
            elif kind == "server_tool_result":
                output = block.get("output")
                if block.get("status") == "error" or not isinstance(output, list):
                    search_failed = True
                    continue
                for result in output:
                    if isinstance(result, dict):
                        agent.add_source(result.get("title") or "Web source", result.get("url", ""))
        await agent.checkpoint("Verifying sources")
        if agent.tool_calls > settings.RESEARCH_MAX_TOOL_CALLS:
            raise ResearchFailure(
                "The tool-call budget was reached. Retry with a narrower question."
            )
        if search_failed:
            raise ResearchFailure(
                f"{agent.label} web search failed or reached its search limit. Partial sources were saved; retry with a narrower question."
            )
        if stop_reason(message) not in ("end_turn", "tool_use", "pause_turn"):
            raise ResearchFailure(
                f"{agent.label} returned an incomplete answer or could not answer this request. Partial sources were saved; try a narrower question."
            )

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Anthropic pauses long server-tool turns; continue them instead of ending the run."""
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or message.tool_calls:
            return None
        if stop_reason(message) != "pause_turn":
            return None
        if self.agent.tool_calls >= settings.RESEARCH_MAX_TOOL_CALLS:
            raise ResearchFailure(
                f"The tool-call budget was reached before {self.agent.label} finished. Retry with a narrower question."
            )
        return {"jump_to": "model"}

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        # Unknown tools and invalid arguments get the same safe answer as the httpx adapters,
        # not LangChain's error text (which can echo arguments back to the model).
        if isinstance(result, ToolMessage) and result.status == "error":
            return ToolMessage(
                content=UNSUPPORTED,
                tool_call_id=result.tool_call_id,
                name=result.name,
                status="error",
            )
        return result


def stop_reason(message: AIMessage) -> str | None:
    reason = message.response_metadata.get("stop_reason")
    return str(reason) if reason is not None else None


def final_turn(messages: list[AnyMessage]) -> list[AIMessage]:
    """Model messages after the last tool round: earlier text is tool-planning narration, but
    text before a `pause_turn` belongs to the answer."""
    turn: list[AIMessage] = []
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            break
        turn.insert(0, message)
    return turn


class LangChainResearchAgent(ResearchAgent):
    """One provider's research loop on LangChain. Subclasses set `provider` and `label`."""

    provider: ClassVar[str]
    label: ClassVar[str]
    rejected: ClassVar[str | None] = None

    def __init__(
        self, progress: Callable[..., Awaitable[None]], *, model: str | None = None, **options: Any
    ):
        super().__init__(progress, model=model or self.default_model(), **options)
        self.transcript: list[AnyMessage] = []

    @classmethod
    def default_model(cls) -> str:
        raise NotImplementedError

    def history_messages(self, prompt: str, history: list[dict[str, str]]) -> list[BaseMessage]:
        turns: list[dict[str, Any]] = [*history, {"role": "user", "content": prompt}]
        # History is trimmed by whole turns, keeping the current question intact.
        while (
            len(turns) > 1
            and len(json.dumps(turns, ensure_ascii=False).encode())
            > settings.RESEARCH_MAX_INPUT_TOKENS // 2
        ):
            del turns[: min(2, len(turns) - 1)]
        return [
            AIMessage(content=turn["content"])
            if turn["role"] == "assistant"
            else HumanMessage(content=turn["content"])
            for turn in turns
        ]

    async def run(self, prompt: str, history: list[dict[str, str]]) -> str:
        try:
            # The middleware generics don't unify under mypy; the list is what create_agent takes.
            middleware: list[Any] = [
                BudgetMiddleware(self),
                ModelCallLimitMiddleware(
                    run_limit=settings.RESEARCH_MAX_MODEL_TURNS, exit_behavior="error"
                ),
            ]
            agent = create_agent(
                model=chat_model(self.provider, self.model, max_tokens=4000),
                tools=make_tools(self),
                system_prompt=self.instructions(),
                middleware=middleware,
            )
            state: Any = {"messages": self.history_messages(prompt, history)}
            result = await agent.ainvoke(
                state,
                config={"recursion_limit": RECURSION_LIMIT},
            )
        except ModelCallLimitExceededError:
            raise ResearchFailure(
                "The research turn limit was reached. Saved evidence is available; try a narrower question."
            ) from None
        except ResearchFailure:
            raise
        except Exception as error:
            raise provider_failure(error, self.label, self.rejected) from None
        self.transcript = result["messages"]
        return self.report(final_turn(self.transcript))

    def report(self, turn: list[AIMessage]) -> str:
        """Join the final turn's text; each safe citation adds a ` [Source N]` marker after
        its text block, and the citation span covers that marker (what the UI highlights)."""
        last = turn[-1] if turn else None
        if last is None or last.tool_calls or stop_reason(last) != "end_turn":
            raise ResearchFailure(f"{self.label} returned no complete report. Please retry.")
        report = ""
        citations: list[dict[str, Any]] = []
        for message in turn:
            for block in message.content_blocks:
                if block.get("type") != "text":
                    continue
                if report:
                    report += "\n\n"
                report += str(block.get("text", ""))
                annotations: Any = block.get("annotations") or []
                for annotation in annotations:
                    url = str(annotation.get("url", ""))
                    if annotation.get("type") != "citation" or not safe_url(url):
                        continue
                    title = str(annotation.get("title") or "Web source")
                    self.add_source(title, url)
                    report += " "
                    start = len(report)
                    report += f"[Source {len(citations) + 1}]"
                    citations.append(
                        Citation(
                            url=url, title=title, start_index=start, end_index=len(report)
                        ).model_dump()
                    )
        if not report.strip():
            raise ResearchFailure(f"{self.label} returned no complete report. Please retry.")
        if not self.evidence:
            report = NO_EVIDENCE + report
            for citation in citations:
                citation["start_index"] += len(NO_EVIDENCE)
                citation["end_index"] += len(NO_EVIDENCE)
        self.citations = citations
        return report


class LangChainAnthropicAgent(LangChainResearchAgent):
    provider = "anthropic"
    label = "Anthropic"
    rejected = "Anthropic rejected the request. Check the model and web-search access in your Anthropic account."

    @classmethod
    def default_model(cls) -> str:
        return settings.ANTHROPIC_RESEARCH_MODEL
