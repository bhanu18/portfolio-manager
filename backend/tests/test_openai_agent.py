"""OpenAI research on LangChain, end to end through the real ChatOpenAI (Responses API).

The OpenAI HTTP API is mocked at the transport, so these cover the request shape (stateless
`store=False`, encrypted reasoning, per-call `max_output_tokens`/`max_tool_calls`), v1 parsing,
citation spans, budgets and safe errors. No network or paid calls.
"""

import json
from pathlib import Path

import httpx2
import langchain_openai.chat_models.base as openai_chat
import pytest

from core.config import settings
from models.research import MarketSnapshot
from service.research import agent as agent_module
from service.research.errors import ProviderUnavailable, ResearchFailure
from service.research.langchain_agent import LangChainOpenAIAgent


@pytest.fixture
def api(monkeypatch):
    responses: list = []
    requests: list[dict] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/responses")
        requests.append(json.loads(request.content))
        assert responses, "Unexpected OpenAI request"
        status, body = responses.pop(0)
        if status == 200:  # real responses have unique ids; LangGraph merges messages by id
            body = {**body, "id": f"resp_{len(requests)}"}
        return httpx2.Response(status, json=body)

    def client(base_url, *args, **kwargs):
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))

    monkeypatch.setattr(openai_chat, "_get_default_async_httpx_client", client)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    return responses, requests


@pytest.fixture
def events():
    return []


@pytest.fixture
def agent(events):
    async def progress(**values):
        events.append(values["stage"])

    return LangChainOpenAIAgent(progress, model="gpt-5-mini")


def response(output, status="completed", input_tokens=100, output_tokens=200):
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-5-mini",
        "output": output,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "incomplete_details": None if status == "completed" else {"reason": "max_output_tokens"},
    }


def message(text, annotations=()):
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": list(annotations)}],
    }


def citation(url, title, start, end):
    return {
        "type": "url_citation",
        "url": url,
        "title": title,
        "start_index": start,
        "end_index": end,
    }


def function_call(name, **arguments):
    call_id = name + json.dumps(arguments, sort_keys=True)
    return {
        "type": "function_call",
        "id": "fc_" + str(abs(hash(call_id)) % 10_000),
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments),
        "status": "completed",
    }


def web_search(*sources):
    return {
        "type": "web_search_call",
        "id": "ws_1",
        "status": "completed",
        "action": {"type": "search", "query": "q", "sources": list(sources)},
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


async def test_tool_call_citation_spans_usage_and_history(agent, api, monkeypatch, events):
    responses, requests = api
    calls = []

    async def market(symbol):
        calls.append(symbol)
        return snapshot(symbol)

    monkeypatch.setattr(agent_module, "stock_snapshot", market)
    text = "  Apple outlook. [1]"
    responses.extend(
        [
            (
                200,
                response(
                    [
                        {
                            "type": "reasoning",
                            "id": "rs_1",
                            "summary": [],
                            "encrypted_content": "ENC",
                        },
                        function_call("stock_snapshot", symbol="AAPL"),
                    ]
                ),
            ),
            (
                200,
                response(
                    [message(text, [citation("https://www.apple.com/newsroom/", "Apple", 17, 20)])]
                ),
            ),
        ]
    )
    report = await agent.run(
        "Research Apple",
        [
            {"role": "user", "content": "Focus on risks"},
            {"role": "assistant", "content": "Consider demand risk"},
        ],
    )
    assert report == text
    assert calls == ["AAPL"]
    assert agent.citations[0]["start_index"] == 17 and agent.citations[0]["end_index"] == 20
    assert report[17:20] == "[1]"
    assert agent.evidence[0]["snapshot"]["units"]["price"] == "USD"
    assert (agent.input_tokens, agent.output_tokens) == (200, 400)
    first, second = requests
    assert first["store"] is False
    assert "reasoning.encrypted_content" in first["include"]
    assert first["max_output_tokens"] == 4000
    assert first["max_tool_calls"] == 8
    assert {t["type"] for t in first["tools"]} == {"web_search", "function"}
    # LangChain sends the system prompt as the first input message (not `instructions`).
    assert first["input"][0]["role"] in ("system", "developer")
    assert "research analyst" in first["input"][0]["content"]
    assert first["input"][1]["content"] == "Focus on risks"
    # Stateless continuation: encrypted reasoning and the tool result go back verbatim.
    assert any(
        i.get("type") == "reasoning" and i.get("encrypted_content") == "ENC"
        for i in second["input"]
    )
    assert second["input"][-1]["type"] == "function_call_output"
    # Per-call cap: min(4000, budget left), 12000 - 200 already spent.
    assert second["max_output_tokens"] == 4000
    assert "Reading stock and ETF data" in events


async def test_etf_comparison_calls_both_tickers(agent, api, monkeypatch):
    responses, _ = api
    symbols = []

    async def market(symbol):
        symbols.append(symbol)
        return snapshot(symbol)

    monkeypatch.setattr(agent_module, "stock_snapshot", market)
    table = "| Fund | Exposure |\n| --- | --- |\n| SPY | Large cap |\n| VTI | Broad market |"
    responses.extend(
        [
            (
                200,
                response(
                    [
                        function_call("stock_snapshot", symbol="SPY"),
                        function_call("stock_snapshot", symbol="VTI"),
                    ]
                ),
            ),
            (200, response([message(table)])),
        ]
    )
    result = await agent.run("Compare SPY and VTI", [])
    assert "| SPY |" in result and symbols == ["SPY", "VTI"]
    assert agent.tool_calls == 2


async def test_treasury_and_web_sources(agent, api, monkeypatch):
    responses, requests = api

    async def treasury(kind):
        assert kind == "bills"
        return snapshot(None, "treasury_bills")

    monkeypatch.setattr(agent_module, "treasury_snapshot", treasury)
    responses.extend(
        [
            (200, response([function_call("treasury_snapshot", kind="bills")])),
            (
                200,
                response(
                    [
                        web_search(
                            {"type": "url", "url": "https://www.treasury.gov", "title": "Treasury"}
                        ),
                        message("Compare coupon-equivalent and 7-day SEC yields with care."),
                    ]
                ),
            ),
        ]
    )
    assert "7-day" in await agent.run("Compare Treasury bills with money-market funds", [])
    assert agent.evidence[0]["snapshot"]["kind"] == "treasury_bills"
    assert agent.evidence[1]["url"] == "https://www.treasury.gov"
    assert agent.tool_calls == 2  # one function call + one hosted web search
    assert requests[1]["max_tool_calls"] == 7


async def test_untitled_sources_use_their_url(agent, api):
    api[0].append(
        (
            200,
            response(
                [web_search({"type": "url", "url": "https://www.sec.gov/x"}), message("Filed.")]
            ),
        )
    )
    await agent.run("Research", [])
    assert agent.evidence[0] == {**agent.evidence[0], "title": "https://www.sec.gov/x"}


@pytest.mark.parametrize(("status", "cooldown"), [(401, 1800), (403, 1800), (429, 60), (500, 60)])
async def test_provider_errors_are_safe(agent, api, status, cooldown):
    api[0].append((status, {"error": {"message": "SECRET upstream body", "type": "x"}}))
    with pytest.raises(ProviderUnavailable) as error:
        await agent.run("Research Apple", [])
    assert error.value.cooldown == cooldown
    assert "SECRET" not in str(error.value)


async def test_quota_and_rejections(agent, api):
    api[0].append(
        (
            429,
            {"error": {"message": "x", "type": "insufficient_quota", "code": "insufficient_quota"}},
        )
    )
    with pytest.raises(ProviderUnavailable) as quota:
        await agent.run("Research", [])
    assert quota.value.cooldown == 1800
    api[0].append((400, {"error": {"message": "SECRET bad schema", "type": "x"}}))
    with pytest.raises(ResearchFailure, match="OpenAI rejected the request") as rejected:
        await agent.run("Research", [])
    assert not isinstance(rejected.value, ProviderUnavailable)
    assert "SECRET" not in str(rejected.value)


async def test_partial_sources_survive_incomplete_response(agent, api):
    api[0].append(
        (
            200,
            response(
                [web_search({"type": "url", "url": "https://www.sec.gov", "title": "SEC filing"})],
                status="incomplete",
            ),
        )
    )
    with pytest.raises(ResearchFailure, match="incomplete"):
        await agent.run("Research Apple", [])
    assert agent.evidence[0]["url"] == "https://www.sec.gov"


async def test_refusal(agent, api):
    refusal = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "refusal", "refusal": "No."}],
    }
    api[0].append((200, response([refusal])))
    with pytest.raises(ResearchFailure, match="could not answer this request"):
        await agent.run("Research", [])


async def test_tool_budget_stops_before_extra_calls(agent, api, monkeypatch):
    responses, requests = api
    monkeypatch.setattr(settings, "RESEARCH_MAX_TOOL_CALLS", 1)
    responses.append(
        (
            200,
            response(
                [
                    function_call("stock_snapshot", symbol="SPY"),
                    function_call("stock_snapshot", symbol="VTI"),
                ]
            ),
        )
    )
    with pytest.raises(ResearchFailure, match="tool-call budget"):
        await agent.run("Compare funds", [])
    assert len(requests) == 1
    assert requests[0]["max_tool_calls"] == 1
    assert not agent.evidence


async def test_input_and_turn_limits(agent, api, monkeypatch):
    responses, requests = api
    monkeypatch.setattr(settings, "RESEARCH_MAX_INPUT_TOKENS", 2000)
    with pytest.raises(ResearchFailure, match="context budget"):
        await agent.run("x" * 6000, [])
    assert not requests
    monkeypatch.setattr(settings, "RESEARCH_MAX_INPUT_TOKENS", 24000)
    monkeypatch.setattr(settings, "RESEARCH_MAX_MODEL_TURNS", 1)
    responses.append((200, response([function_call("unknown")])))
    with pytest.raises(ResearchFailure, match="turn limit"):
        await agent.run("Research", [])
    assert len(requests) == 1


async def test_unsourced_answer_shifts_citation_spans(agent, api):
    # A citation with an unsafe URL is dropped, so no evidence: the prefix is added.
    api[0].append((200, response([message("Hello world", [citation("javascript:x", "X", 0, 5)])])))
    report = await agent.run("hi", [])
    assert report == "No external evidence was retrieved for this response.\n\nHello world"
    assert agent.citations == []


async def test_output_budget_caps_each_call(agent, api, monkeypatch):
    """The per-call cap must reach the request: LangChain would otherwise keep the model's."""
    agent.output_budget = 4500
    api[0].extend(
        [
            (
                200,
                response(
                    [web_search({"type": "url", "url": "https://a.example"})], output_tokens=3800
                ),
            ),
            (200, response([message("Short.")], output_tokens=100)),
        ]
    )
    # A search-only turn completes with no message and no tool call, so it ends the run;
    # check the cap on a direct second run instead.
    with pytest.raises(ResearchFailure):
        await agent.run("Research", [])
    await agent.run("Research", [])
    assert [r["max_output_tokens"] for r in api[1]] == [4000, 700]


async def test_citation_spans_are_offset_across_text_blocks(agent, api):
    second = {
        **message("See filing.", [citation("https://www.sec.gov", "SEC", 4, 10)]),
        "id": "msg_2",
    }
    api[0].append((200, response([message("First part."), second])))
    report = await agent.run("Research", [])
    assert report == "First part.\n\nSee filing."
    (cited,) = agent.citations
    assert report[cited["start_index"] : cited["end_index"]] == "filing"


FIXTURE = Path(__file__).parent / "fixtures" / "langchain" / "openai_web.json"


@pytest.mark.skipif(
    not FIXTURE.exists(), reason="record with: python -m evals.record_fixture openai"
)
async def test_recorded_openai_responses_replay(agent, api):
    """Real OpenAI responses (recorded once) must parse into a report with valid spans."""
    from evals.fixtures import offline_market_data

    recorded = json.loads(FIXTURE.read_text())
    api[0].extend((200, body) for body in recorded["responses"])
    with offline_market_data():
        report = await agent.run(recorded["prompt"], [])
    assert report.strip()
    for item in agent.citations:
        if item["start_index"] is not None:
            assert 0 <= item["start_index"] < item["end_index"] <= len(report)
    assert all(item["url"].startswith("https://") for item in agent.evidence)
