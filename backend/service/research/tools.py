"""The read-only market tools as LangChain tools, plus each provider's native web search.

Tools are closures over a `ResearchAgent`, so every call goes through `market_tool`: the same
progress stages, evidence recording, budgets and safe error JSON as the httpx adapters.
Descriptions come from `agent.TOOLS` so every adapter shows models identical text.
"""

from typing import Any, Literal

from langchain_core.tools import BaseTool, tool

from service.research.agent import TOOLS, ResearchAgent

DESCRIPTIONS = {item["name"]: item["description"] for item in TOOLS if item["type"] == "function"}


def make_tools(agent: ResearchAgent) -> list[BaseTool]:
    """The market tools this agent may use (the orchestrator narrows them per step)."""

    @tool(description=DESCRIPTIONS["stock_snapshot"])
    async def stock_snapshot(symbol: str) -> str:
        return await agent.market_tool("stock_snapshot", {"symbol": symbol})

    @tool(description=DESCRIPTIONS["investment_analysis"])
    async def investment_analysis(symbol: str) -> str:
        return await agent.market_tool("investment_analysis", {"symbol": symbol})

    @tool(description=DESCRIPTIONS["treasury_snapshot"])
    async def treasury_snapshot(kind: Literal["curve", "bills"]) -> str:
        return await agent.market_tool("treasury_snapshot", {"kind": kind})

    tools: list[BaseTool] = [stock_snapshot, investment_analysis, treasury_snapshot]
    return [item for item in tools if agent.tool_allowed(item.name)]


def web_search_tool(provider: str, remaining_uses: int) -> dict[str, Any] | None:
    """Provider-hosted web search, bound next to the market tools. Local models have none."""
    if provider == "openai":
        return {"type": "web_search"}
    if provider == "anthropic":
        return {"type": "web_search_20250305", "name": "web_search", "max_uses": remaining_uses}
    return None
