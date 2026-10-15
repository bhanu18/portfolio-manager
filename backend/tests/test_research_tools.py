"""LangChain market tools must behave exactly like the httpx adapters' tool execution."""

import json
import subprocess
import sys
from pathlib import Path

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


async def test_tool_call_matches_execute_tool(make_agent, monkeypatch):
    async def fetch(symbol):
        return snapshot(symbol)

    monkeypatch.setattr(module, "stock_snapshot", fetch)
    via_langchain, via_httpx = make_agent(), make_agent()
    (stock, *_) = make_tools(via_langchain)
    result = await stock.ainvoke({"symbol": "AAPL"})
    expected = await via_httpx.execute_tool(
        {"name": "stock_snapshot", "arguments": json.dumps({"symbol": "AAPL"})}
    )
    assert result == expected
    assert via_langchain.evidence == via_httpx.evidence
    assert (
        via_langchain.events
        == via_httpx.events
        == [
            "Reading stock and ETF data",
            "Checking market evidence",
        ]
    )


async def test_upstream_failures_return_the_same_safe_json(make_agent, monkeypatch):
    async def broken(symbol):
        raise RuntimeError("secret upstream payload")

    monkeypatch.setattr(module, "investment_snapshot", broken)
    agent = make_agent()
    tool = next(t for t in make_tools(agent) if t.name == "investment_analysis")
    result = await tool.ainvoke({"symbol": "AAPL"})
    assert "secret" not in result
    assert result == await make_agent().execute_tool(
        {"name": "investment_analysis", "arguments": json.dumps({"symbol": "AAPL"})}
    )
    assert agent.evidence == []


def test_web_search_per_provider():
    assert web_search_tool("openai", 3) == {"type": "web_search"}
    assert web_search_tool("anthropic", 3) == {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 3,
    }
    assert web_search_tool("local", 3) is None


def test_running_app_does_not_load_langchain_yet():
    """PR 1 adds building blocks only: the worker and API must not import LangChain."""
    code = (
        "import sys, main, service.research.worker; "
        "print(any(m.startswith(('langchain', 'langgraph')) for m in sys.modules))"
    )
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
