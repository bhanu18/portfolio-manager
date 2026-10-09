"""Research provider and agent tests are deterministic and never call paid APIs."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from core.config import settings
from models.research import MarketSnapshot, ResearchSubmit
from service.research import agent as module
from service.research.agent import ResearchAgent, ResearchFailure
from service.research.providers import number, parse_treasury, safe_url, stock_snapshot_sync


@pytest.fixture
def events():
    return []


@pytest.fixture
def agent(events):
    async def progress(**values):
        events.append(values)

    return ResearchAgent(progress)


@pytest.fixture
def provider(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    responses = []

    def handle(request):
        requests.append(json.loads(request.content))
        assert responses, "Unexpected provider request"
        status, data = responses.pop(0)
        return httpx.Response(status, json=data)

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    return responses, requests


def answer(text="## Summary\nA sourced brief.", annotations=None, **kwargs):
    return {
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 200},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text, "annotations": annotations or []}
                ],
            }
        ],
        **kwargs,
    }


def tool(name, **arguments):
    return {
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(arguments),
        "call_id": name + str(arguments),
    }


def snapshot(symbol="AAPL", kind="stock_etf"):
    return MarketSnapshot(
        kind=kind,
        symbol=symbol,
        observed_at="2026-10-07",
        retrieved_at="2026-10-08T00:00:00+00:00",
        source_url="https://example.com/market",
        values={"price": 100},
        units={"price": "USD"},
    )


async def test_stock_tool_citations_usage_and_followup_context(
    agent, provider, monkeypatch, events
):
    responses, requests = provider
    calls = []

    async def market(symbol):
        calls.append(symbol)
        return snapshot(symbol)

    monkeypatch.setattr(module, "stock_snapshot", market)
    responses.append((200, answer(output=[tool("stock_snapshot", symbol="AAPL")])))
    text = "  Apple outlook. [1]"
    annotations = [
        {
            "type": "url_citation",
            "url": "https://www.apple.com/newsroom/",
            "title": "Apple",
            "start_index": 17,
            "end_index": 20,
        }
    ]
    responses.append((200, answer(text, annotations)))
    report = await agent.run(
        "Research Apple",
        [
            {"role": "user", "content": "Focus on risks"},
            {"role": "assistant", "content": "Consider demand risk"},
        ],
    )
    assert report == text
    assert calls == ["AAPL"]
    assert agent.citations[0]["start_index"] == 17
    assert agent.evidence[0]["snapshot"]["units"]["price"] == "USD"
    assert agent.input_tokens == 200 and agent.output_tokens == 400
    assert requests[0]["input"][0]["content"] == "Focus on risks"
    assert requests[0]["store"] is False
    assert requests[1]["input"][-1]["type"] == "function_call_output"
    assert any(event["stage"] == "Reading stock and ETF data" for event in events)


async def test_etf_comparison_calls_both_tickers(agent, provider, monkeypatch):
    responses, _ = provider
    symbols = []

    async def market(symbol):
        symbols.append(symbol)
        return snapshot(symbol)

    monkeypatch.setattr(module, "stock_snapshot", market)
    responses.extend(
        [
            (
                200,
                answer(
                    output=[
                        tool("stock_snapshot", symbol="SPY"),
                        tool("stock_snapshot", symbol="VTI"),
                    ]
                ),
            ),
            (
                200,
                answer(
                    "| Fund | Exposure |\n| --- | --- |\n| SPY | Large cap |\n| VTI | Broad market |"
                ),
            ),
        ]
    )
    result = await agent.run("Compare SPY and VTI", [])
    assert "| SPY |" in result and symbols == ["SPY", "VTI"]
    assert agent.tool_calls == 2


async def test_treasury_money_market_and_web_sources(agent, provider, monkeypatch):
    responses, _ = provider

    async def treasury(kind):
        assert kind == "bills"
        return snapshot(None, "treasury_bills")

    monkeypatch.setattr(module, "treasury_snapshot", treasury)
    responses.extend(
        [
            (200, answer(output=[tool("treasury_snapshot", kind="bills")])),
            (
                200,
                answer(
                    output=[
                        {
                            "type": "web_search_call",
                            "action": {
                                "sources": [
                                    {"url": "https://www.treasury.gov", "title": "Treasury"}
                                ]
                            },
                        },
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Compare coupon-equivalent and 7-day SEC yields with care.",
                                    "annotations": [],
                                }
                            ],
                        },
                    ]
                ),
            ),
        ]
    )
    assert "7-day" in await agent.run("Compare Treasury bills with money-market funds", [])
    assert agent.evidence[0]["snapshot"]["kind"] == "treasury_bills"
    assert agent.evidence[1]["url"] == "https://www.treasury.gov"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_are_safe(agent, provider, status):
    responses, _ = provider
    responses.append((status, {"error": "SECRET upstream body"}))
    with pytest.raises(ResearchFailure) as error:
        await agent.run("Research Apple", [])
    assert "SECRET" not in str(error.value)


async def test_partial_sources_survive_incomplete_response(agent, provider):
    responses, _ = provider
    responses.append(
        (
            200,
            answer(
                status="incomplete",
                output=[
                    {
                        "type": "web_search_call",
                        "action": {
                            "sources": [{"url": "https://www.sec.gov", "title": "SEC filing"}]
                        },
                    }
                ],
            ),
        )
    )
    with pytest.raises(ResearchFailure, match="incomplete"):
        await agent.run("Research Apple", [])
    assert agent.evidence[0]["url"] == "https://www.sec.gov"


async def test_failed_tool_is_explicit_and_unknown_tool_cannot_execute(agent, monkeypatch):
    async def unavailable(symbol):
        raise RuntimeError("secret provider body")

    monkeypatch.setattr(module, "stock_snapshot", unavailable)
    result = await agent.execute_tool(tool("stock_snapshot", symbol="AAPL"))
    assert "unavailable" in result and "secret" not in result
    result = await agent.execute_tool(tool("execute_shell", command="printenv"))
    assert "Unsupported" in result


async def test_limits_stop_before_extra_tools_or_provider_calls(agent, provider, monkeypatch):
    responses, requests = provider
    monkeypatch.setattr(settings, "RESEARCH_MAX_TOOL_CALLS", 1)
    responses.append(
        (
            200,
            answer(
                output=[tool("stock_snapshot", symbol="SPY"), tool("stock_snapshot", symbol="VTI")]
            ),
        )
    )
    with pytest.raises(ResearchFailure, match="tool-call budget"):
        await agent.run("Compare funds", [])
    assert len(requests) == 1
    assert requests[0]["max_tool_calls"] == 1
    assert not agent.evidence


async def test_input_and_turn_limits(agent, provider, monkeypatch):
    responses, requests = provider
    monkeypatch.setattr(settings, "RESEARCH_MAX_INPUT_TOKENS", 2000)
    with pytest.raises(ResearchFailure, match="context budget"):
        await agent.run("x" * 6000, [])
    assert not requests
    monkeypatch.setattr(settings, "RESEARCH_MAX_INPUT_TOKENS", 24000)
    monkeypatch.setattr(settings, "RESEARCH_MAX_MODEL_TURNS", 1)
    responses.append((200, answer(output=[tool("unknown")])))
    with pytest.raises(ResearchFailure, match="turn limit"):
        await agent.run("Research", [])
    assert len(requests) == 1


@pytest.mark.parametrize("kind,field", [("curve", "BC_10YEAR"), ("bills", "ROUND_CE_13WK")])
def test_treasury_observation_dates_units_nulls_and_staleness(kind, field):
    xml = f"""<feed xmlns:m="urn:metadata" xmlns:d="urn:data"><entry><m:properties><d:NEW_DATE>2026-10-01T00:00:00</d:NEW_DATE><d:{field}>4.2</d:{field}><d:BC_2YEAR /></m:properties></entry></feed>""".encode()
    result = parse_treasury(xml, kind, datetime(2026, 10, 8, tzinfo=UTC))
    assert result.observed_at == "2026-10-01"
    assert result.values[field] == 4.2
    assert result.values["BC_2YEAR"] is None
    assert result.units[field] == "percent per annum"
    assert result.warnings
    assert "bank-discount" in result.definitions["bill_yields"]


def test_treasury_rejects_unsafe_or_empty_xml():
    for xml in (b"<!DOCTYPE foo><feed/>", b"<feed/>"):
        with pytest.raises(ValueError):
            parse_treasury(xml, "curve", datetime.now(UTC))


def test_stock_snapshot_normalizes_missing_stale_and_nonfinite(monkeypatch):
    class FakeTicker:
        def get_info(self):
            return {
                "shortName": "Example",
                "regularMarketTime": 1,
                "regularMarketPrice": float("nan"),
                "currency": "USD",
            }

    monkeypatch.setattr("service.research.providers.yf.Ticker", lambda _: FakeTicker())
    result = stock_snapshot_sync("aapl")
    assert result.symbol == "AAPL" and result.values["price"] is None
    assert len(result.warnings) == 3
    assert number(float("inf")) is None
    assert not safe_url("javascript:alert(1)")
    assert not safe_url("https://user:password@example.com")
    with pytest.raises(ValueError):
        stock_snapshot_sync("https://localhost")


def test_question_validation():
    with pytest.raises(ValueError):
        ResearchSubmit(prompt="   ", request_id="bad")
