import json

import httpx
import pytest

from core.config import settings
from service.research.agent import ResearchFailure
from service.research.anthropic_agent import AnthropicResearchAgent


@pytest.fixture
def provider(monkeypatch):
    original = httpx.AsyncClient
    responses, requests = [], []

    def handle(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["anthropic-version"] == "2023-06-01"
        requests.append(json.loads(request.content))
        status, data = responses.pop(0)
        return httpx.Response(status, json=data)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    return responses, requests


@pytest.fixture
def agent():
    async def progress(**values):
        pass

    return AnthropicResearchAgent(progress, model="configured-claude")


def answer(content, stop="end_turn"):
    return {
        "content": content,
        "stop_reason": stop,
        "usage": {"input_tokens": 100, "output_tokens": 100},
    }


async def test_citations_and_pause_preserve_sources(agent, provider):
    responses, requests = provider
    source = {
        "type": "web_search_tool_result",
        "tool_use_id": "search1",
        "content": [{"url": "https://www.sec.gov", "title": "SEC", "encrypted_content": "opaque"}],
    }
    responses.extend(
        [
            (
                200,
                answer(
                    [
                        {
                            "type": "server_tool_use",
                            "id": "search1",
                            "name": "web_search",
                            "input": {"query": "Apple"},
                        },
                        source,
                    ],
                    "pause_turn",
                ),
            ),
            (
                200,
                answer(
                    [
                        {
                            "type": "text",
                            "text": "📊 Apple findings.",
                            "citations": [{"url": "https://www.sec.gov", "title": "SEC"}],
                        }
                    ]
                ),
            ),
        ]
    )
    report = await agent.run(
        "Apple",
        [
            {"role": "user", "content": "Focus on risk"},
            {"role": "assistant", "content": "Prior brief"},
        ],
    )
    citation = agent.citations[0]
    assert report[citation["start_index"] : citation["end_index"]] == "[Source 1]"
    assert requests[1]["messages"][-1]["content"][-1] == source
    assert requests[0]["model"] == "configured-claude"
    assert requests[0]["messages"][0]["content"] == "Focus on risk"
    assert agent.tool_calls == 1 and agent.input_tokens == 200
    assert requests[0]["tools"][0]["type"] == "web_search_20250305"


async def test_client_tools_continue_with_matching_results(agent, provider, monkeypatch):
    responses, requests = provider

    async def execute(call):
        assert call["name"] == "stock_snapshot"
        return '{"price":100}'

    monkeypatch.setattr(agent, "execute_tool", execute)
    responses.extend(
        [
            (
                200,
                answer(
                    [
                        {
                            "type": "tool_use",
                            "id": "tool1",
                            "name": "stock_snapshot",
                            "input": {"symbol": "AAPL"},
                        }
                    ],
                    "tool_use",
                ),
            ),
            (200, answer([{"type": "text", "text": "Analysis"}])),
        ]
    )
    assert "Analysis" in await agent.run("Research Apple", [])
    assert requests[1]["messages"][-1]["content"][0]["tool_use_id"] == "tool1"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_safe_errors(agent, provider, status):
    provider[0].append((status, {"error": "SECRET"}))
    with pytest.raises(ResearchFailure) as error:
        await agent.run("Research", [])
    assert "SECRET" not in str(error.value)


async def test_search_failure_retains_partial_evidence(agent, provider):
    provider[0].append(
        (
            200,
            answer(
                [
                    {
                        "type": "web_search_tool_result",
                        "content": [{"url": "https://www.sec.gov", "title": "SEC"}],
                    },
                    {
                        "type": "web_search_tool_result",
                        "content": {
                            "type": "web_search_tool_result_error",
                            "error_code": "max_uses_exceeded",
                        },
                    },
                ]
            ),
        )
    )
    with pytest.raises(ResearchFailure, match="search failed"):
        await agent.run("Research", [])
    assert agent.evidence[0]["title"] == "SEC"


async def test_limits(agent, provider, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MAX_TOOL_CALLS", 1)
    provider[0].append((200, answer([{"type": "server_tool_use", "id": str(i)} for i in range(2)])))
    with pytest.raises(ResearchFailure, match="tool-call budget"):
        await agent.run("Research", [])
    assert len(provider[1]) == 1
