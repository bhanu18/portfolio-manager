"""Anthropic research on LangChain, end to end through the real ChatAnthropic client.

The Anthropic HTTP API is mocked at the transport, so these tests cover what the httpx adapter
tests covered: request shape, v1 content-block parsing, the round trip of server tool results,
budgets, citations and safe errors. No network or paid calls.
"""

import json
from pathlib import Path

import httpx2
import langchain_anthropic.chat_models as anthropic_chat
import pytest

from core.config import settings
from models.research import MarketSnapshot
from service.research import agent as agent_module
from service.research.errors import ProviderUnavailable, ResearchFailure
from service.research.langchain_agent import LangChainAnthropicAgent

FIXTURE = Path(__file__).parent / "fixtures" / "langchain" / "anthropic_web.json"


@pytest.fixture
def api(monkeypatch):
    """Queue raw Messages API responses; capture each request body."""
    responses: list[tuple[int, dict]] = []
    requests: list[dict] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/messages"
        requests.append(json.loads(request.content))
        status, body = responses.pop(0)
        if status == 200:  # real responses have unique ids; LangGraph merges messages by id
            body = {**body, "id": f"msg_{len(requests)}"}
        return httpx2.Response(status, json=body)

    def client(**params):
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(handle), base_url=params["base_url"]
        )

    monkeypatch.setattr(anthropic_chat, "_get_default_async_httpx_client", client)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    return responses, requests


@pytest.fixture
def stages():
    return []


@pytest.fixture
def agent(stages):
    async def progress(**values):
        stages.append(values["stage"])

    return LangChainAnthropicAgent(progress, model="configured-claude")


def answer(content, stop="end_turn", input_tokens=100, output_tokens=100):
    return {
        "id": "msg",
        "type": "message",
        "role": "assistant",
        "model": "configured-claude",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def search(call_id="search1", url="https://www.sec.gov", title="SEC"):
    return [
        {"type": "server_tool_use", "id": call_id, "name": "web_search", "input": {"query": "q"}},
        {
            "type": "web_search_tool_result",
            "tool_use_id": call_id,
            "content": [
                {
                    "type": "web_search_result",
                    "url": url,
                    "title": title,
                    "encrypted_content": "opaque",
                }
            ],
        },
    ]


def text(value, citations=()):
    block = {"type": "text", "text": value}
    if citations:
        block["citations"] = [
            {
                "type": "web_search_result_location",
                "url": url,
                "title": title,
                "cited_text": "x",
                "encrypted_index": "e",
            }
            for url, title in citations
        ]
    return block


def tool_use(call_id, name, **arguments):
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


async def test_pause_turn_continues_and_citations_mark_sources(agent, api, stages):
    responses, requests = api
    responses.extend(
        [
            answer(search(), "pause_turn"),
            answer([text("📊 Apple findings.", [("https://www.sec.gov", "SEC")])]),
        ]
    )
    responses[:] = [(200, body) for body in responses]
    report = await agent.run(
        "Apple",
        [
            {"role": "user", "content": "Focus on risk"},
            {"role": "assistant", "content": "Prior brief"},
        ],
    )
    citation = agent.citations[0]
    assert report[citation["start_index"] : citation["end_index"]] == "[Source 1]"
    assert report.startswith("📊 Apple findings. [Source 1]")
    first, second = requests
    assert first["model"] == "configured-claude"
    assert first["messages"][0]["content"] == "Focus on risk"
    assert first["tools"][0] == {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}
    assert first["max_tokens"] == 4000
    # The paused turn goes back verbatim, encrypted search content included.
    paused = second["messages"][-1]
    assert paused["role"] == "assistant"
    assert any(
        block.get("type") == "web_search_tool_result"
        and block["content"][0]["encrypted_content"] == "opaque"
        for block in paused["content"]
    )
    assert second["tools"][0]["max_uses"] == 7  # one search spent
    assert (agent.tool_calls, agent.model_turns, agent.input_tokens) == (1, 2, 200)
    assert agent.evidence[0]["url"] == "https://www.sec.gov"
    assert stages[:2] == ["Searching sources and drafting analysis", "Verifying sources"]


async def test_client_tools_run_and_only_the_final_turn_is_the_report(
    agent, api, monkeypatch, stages
):
    responses, requests = api

    async def snapshot(symbol):
        return MarketSnapshot(
            kind="stock_etf",
            symbol=symbol,
            retrieved_at="2026-10-15T00:00:00+00:00",
            source_url="https://finance.yahoo.com/quote/AAPL/",
            values={"price": 100},
        )

    monkeypatch.setattr(agent_module, "stock_snapshot", snapshot)
    responses.extend(
        [
            (
                200,
                answer(
                    [text("Let me check."), tool_use("tool1", "stock_snapshot", symbol="AAPL")],
                    "tool_use",
                ),
            ),
            (200, answer([text("Apple trades at $100.")])),
        ]
    )
    report = await agent.run("Research Apple", [])
    assert report == "Apple trades at $100."  # planning narration is dropped
    result = requests[1]["messages"][-1]["content"][0]
    assert (result["type"], result["tool_use_id"]) == ("tool_result", "tool1")
    assert json.loads(result["content"])["symbol"] == "AAPL"
    assert agent.evidence[0]["snapshot"]["values"]["price"] == 100
    assert "Reading stock and ETF data" in stages


async def test_unknown_tools_and_bad_arguments_get_the_safe_answer(agent, api):
    responses, requests = api
    responses.extend(
        [
            (
                200,
                answer(
                    [
                        tool_use("t1", "execute_shell", command="printenv"),
                        tool_use("t2", "treasury_snapshot", kind="secrets"),
                    ],
                    "tool_use",
                ),
            ),
            (200, answer([text("Done.")])),
        ]
    )
    await agent.run("Research", [])
    results = requests[1]["messages"][-1]["content"]
    assert [json.loads(r["content"]) for r in results] == [
        {"error": "Unsupported read-only tool or arguments"}
    ] * 2


@pytest.mark.parametrize(
    ("status", "cooldown"), [(401, 1800), (403, 1800), (429, 60), (500, 60), (529, 60)]
)
async def test_account_errors_fail_over_without_leaking(agent, api, status, cooldown):
    api[0].append((status, {"type": "error", "error": {"type": "x", "message": "SECRET"}}))
    with pytest.raises(ProviderUnavailable) as raised:
        await agent.run("Research", [])
    assert raised.value.cooldown == cooldown
    assert "SECRET" not in str(raised.value)


async def test_credit_exhaustion_and_rejections(agent, api):
    credit = {"type": "error", "error": {"type": "x", "message": "Your credit balance is too low"}}
    api[0].append((400, credit))
    with pytest.raises(ProviderUnavailable) as raised:
        await agent.run("Research", [])
    assert raised.value.cooldown == 1800
    api[0].append((400, {"type": "error", "error": {"type": "x", "message": "SECRET schema"}}))
    with pytest.raises(ResearchFailure, match="web-search access") as rejected:
        await agent.run("Research", [])
    assert not isinstance(rejected.value, ProviderUnavailable)


async def test_search_failure_keeps_partial_evidence(agent, api):
    error = {
        "type": "web_search_tool_result",
        "tool_use_id": "s2",
        "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"},
    }
    api[0].append(
        (
            200,
            answer(
                [
                    *search(),
                    {"type": "server_tool_use", "id": "s2", "name": "web_search", "input": {}},
                    error,
                ]
            ),
        )
    )
    with pytest.raises(ResearchFailure, match="search failed"):
        await agent.run("Research", [])
    assert agent.evidence[0]["title"] == "SEC"


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
async def test_incomplete_or_refused_answers(agent, api, stop):
    api[0].append((200, answer([text("Partial")], stop)))
    with pytest.raises(ResearchFailure, match="incomplete answer"):
        await agent.run("Research", [])


async def test_tool_budget_counts_web_searches(agent, api, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MAX_TOOL_CALLS", 1)
    api[0].append(
        (200, answer([*search("a"), *search("b", url="https://example.com/b")], "pause_turn"))
    )
    with pytest.raises(ResearchFailure, match="tool-call budget"):
        await agent.run("Research", [])
    assert len(api[1]) == 1


async def test_pause_with_spent_budget_stops(agent, api, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MAX_TOOL_CALLS", 1)
    api[0].append((200, answer(search(), "pause_turn")))
    with pytest.raises(ResearchFailure, match="before Anthropic finished"):
        await agent.run("Research", [])


async def test_turn_limit(agent, api, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MAX_MODEL_TURNS", 1)
    api[0].extend([(200, answer(search(), "pause_turn")), (200, answer([text("late")]))])
    with pytest.raises(ResearchFailure, match="turn limit"):
        await agent.run("Research", [])
    assert len(api[1]) == 1


async def test_output_budget_caps_each_call(agent, api, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MAX_OUTPUT_TOKENS", 4500)
    agent.output_budget = 4500
    api[0].extend(
        [
            (200, answer(search(), "pause_turn", output_tokens=3800)),
            (200, answer([text("Short.")], output_tokens=100)),
        ]
    )
    await agent.run("Research", [])
    assert [r["max_tokens"] for r in api[1]] == [4000, 700]
    agent2 = LangChainAnthropicAgent(agent.progress, model="m")
    agent2.output_budget, agent2.output_tokens = 4500, 4100
    with pytest.raises(ResearchFailure, match="response token budget"):
        await agent2.run("Research", [])


async def test_context_budget(agent, api, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MAX_INPUT_TOKENS", 2000)
    with pytest.raises(ResearchFailure, match="context budget"):
        await agent.run("Research", [])
    assert api[1] == []


async def test_unsourced_answers_are_labelled(agent, api):
    api[0].append((200, answer([text("Please name a ticker.")])))
    report = await agent.run("stocks?", [])
    assert (
        report == "No external evidence was retrieved for this response.\n\nPlease name a ticker."
    )


async def test_empty_or_unfinished_final_turn(agent, api):
    api[0].append((200, answer([], "end_turn")))
    with pytest.raises(ResearchFailure, match="no complete report"):
        await agent.run("Research", [])


async def test_orchestrator_tools_restrictions_apply(api, stages):
    async def progress(**values):
        pass

    writer = LangChainAnthropicAgent(progress, model="m", allowed_tools=set())
    api[0].append((200, answer([text("From notes.")])))
    await writer.run("Research", [])
    assert "tools" not in api[1][0] or api[1][0]["tools"] == []
    web = LangChainAnthropicAgent(progress, model="m", allowed_tools={"web_search"})
    api[0].append((200, answer([text("Notes.")])))
    await web.run("Research", [])
    assert [t["name"] for t in api[1][1]["tools"]] == ["web_search"]


@pytest.mark.skipif(not FIXTURE.exists(), reason="record with: python -m evals.record_fixture")
async def test_recorded_anthropic_responses_replay(agent, api, monkeypatch):
    """Real Anthropic responses (recorded once) must parse into a cited report."""
    from evals.fixtures import offline_market_data

    recorded = json.loads(FIXTURE.read_text())
    api[0].extend((200, body) for body in recorded["responses"])
    with offline_market_data():
        report = await agent.run(recorded["prompt"], [])
    assert report.strip()
    for citation in agent.citations:
        assert report[citation["start_index"] : citation["end_index"]].startswith("[Source ")
    assert all(item["url"].startswith("https://") for item in agent.evidence)
