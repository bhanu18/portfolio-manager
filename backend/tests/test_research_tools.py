"""LangChain market tools must behave exactly like the httpx adapters' tool execution."""

import json

import pytest

from models.research import MarketSnapshot
from service.research import agent as module
from service.research.agent import TOOLS, ResearchAgent
from service.research.tools import make_tools, web_search_tool


def snapshot(symbol):
    return MarketSnapshot(
        kind="stock_etf",
        symbol=symbol,
        retrieved_at="2026-10-15T00:00:00+00:00",
        source_url=f"https://example.com/{symbol}",
        values={"price": 100},
    )


@pytest.fixture
def make_agent():
    def build(**options):
        events = []

        async def progress(**values):
            events.append(values["stage"])

        agent = ResearchAgent(progress, **options)
        agent.events = events
        return agent

    return build


def test_names_descriptions_and_schema_match_the_httpx_tools(make_agent):
    tools = make_tools(make_agent())
    expected = {t["name"]: t for t in TOOLS if t["type"] == "function"}
    assert [t.name for t in tools] == list(expected)
    for item in tools:
        assert item.description == expected[item.name]["description"]
        params = expected[item.name]["parameters"]
        schema = item.args_schema.model_json_schema()
        assert set(schema["properties"]) == set(params["properties"])
        assert schema["required"] == params["required"]
    kind = next(t for t in tools if t.name == "treasury_snapshot")
    assert kind.args_schema.model_json_schema()["properties"]["kind"]["enum"] == ["curve", "bills"]


def test_allowed_tools_narrow_the_set(make_agent):
    assert [t.name for t in make_tools(make_agent(allowed_tools={"stock_snapshot"}))] == [
        "stock_snapshot"
    ]
    assert make_tools(make_agent(allowed_tools={"web_search"})) == []


async def test_tool_call_records_evidence_and_reports_progress(make_agent, monkeypatch):
    async def fetch(symbol):
        return snapshot(symbol)

    monkeypatch.setattr(module, "stock_snapshot", fetch)
    agent = make_agent()
    (stock, *_) = make_tools(agent)
    result = json.loads(await stock.ainvoke({"symbol": "AAPL"}))
    assert (result["symbol"], result["values"]["price"]) == ("AAPL", 100)
    assert agent.evidence[0]["url"] == "https://example.com/AAPL"
    assert agent.events == ["Reading stock and ETF data", "Checking market evidence"]


async def test_upstream_failures_return_safe_json(make_agent, monkeypatch):
    async def broken(symbol):
        raise RuntimeError("secret upstream payload")

    monkeypatch.setattr(module, "investment_snapshot", broken)
    monkeypatch.setattr(module, "stock_snapshot", broken)
    agent = make_agent()
    tools = {t.name: t for t in make_tools(agent)}
    analysis = await tools["investment_analysis"].ainvoke({"symbol": "AAPL"})
    stock = await tools["stock_snapshot"].ainvoke({"symbol": "AAPL"})
    assert "secret" not in analysis + stock
    assert json.loads(stock) == {"error": "Market provider failed. This data is unavailable."}
    assert agent.evidence == []


async def test_market_tool_rejects_unknown_tools_and_arguments(make_agent):
    agent = make_agent()
    unsupported = {"error": "Unsupported read-only tool or arguments"}
    assert json.loads(await agent.market_tool("execute_shell", {"command": "env"})) == unsupported
    assert json.loads(await agent.market_tool("stock_snapshot", {"ticker": "A"})) == unsupported
    restricted = make_agent(allowed_tools={"treasury_snapshot"})
    assert (
        json.loads(await restricted.market_tool("stock_snapshot", {"symbol": "A"})) == unsupported
    )


def test_web_search_per_provider():
    assert web_search_tool("openai", 3) == {"type": "web_search"}
    assert web_search_tool("anthropic", 3) == {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 3,
    }
    assert web_search_tool("local", 3) is None
