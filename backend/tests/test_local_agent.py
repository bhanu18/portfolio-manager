"""Local (OpenAI-compatible) adapter tests are deterministic and never reach a model server."""

import json

import httpx
import pytest

from core.config import settings
from models.research import MarketSnapshot
from service.research import agent as agent_module
from service.research import local_agent as module
from service.research.agent import ResearchFailure
from service.research.local_agent import LocalResearchAgent, local_json


@pytest.fixture(autouse=True)
def local_settings(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://ollama.test/v1/")
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "qwen3:8b")


@pytest.fixture
def server(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    responses = []

    def handle(request):
        requests.append((str(request.url), json.loads(request.content)))
        assert responses, "Unexpected local model request"
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, data = response
        return httpx.Response(status, json=data)

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    return responses, requests


@pytest.fixture
def agent():
    async def progress(**values):
        pass

    return LocalResearchAgent(progress)


def reply(content="", tool_calls=None, finish="stop"):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }


async def test_tool_loop_strips_thinking_and_counts_usage(agent, server, monkeypatch):
    responses, requests = server

    async def market(symbol):
        return MarketSnapshot(
            kind="stock_etf",
            symbol=symbol,
            retrieved_at="2026-10-08T00:00:00+00:00",
            source_url="https://example.com/market",
            values={"price": 100},
        )

    monkeypatch.setattr(agent_module, "stock_snapshot", market)
    call = {
        "id": "call_1",
        "type": "function",
        # Ollama may return parsed arguments rather than a JSON string.
        "function": {"name": "stock_snapshot", "arguments": {"symbol": "AAPL"}},
    }
    responses.append((200, reply(tool_calls=[call], finish="tool_calls")))
    responses.append((200, reply("<think>plan</think>\n## Summary\nAAPL at 100.")))
    report = await agent.run("AAPL price?", [])
    assert report == "## Summary\nAAPL at 100."
    assert requests[0][0] == "http://ollama.test/v1/chat/completions"
    first = requests[0][1]
    assert first["model"] == "qwen3:8b"
    assert "Web search is unavailable" in first["messages"][0]["content"]
    assert {tool["function"]["name"] for tool in first["tools"]} == {
        "stock_snapshot",
        "investment_analysis",
        "treasury_snapshot",
    }
    tool_message = requests[1][1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_1"
    assert json.loads(tool_message["content"])["symbol"] == "AAPL"
    assert (agent.input_tokens, agent.output_tokens, agent.tool_calls) == (100, 40, 1)
    assert agent.evidence[0]["title"] == "AAPL"


async def test_restricted_tools_omit_tool_list(server):
    responses, requests = server

    async def progress(**values):
        pass

    agent = LocalResearchAgent(progress, allowed_tools=set(), extra_instructions="DATA")
    responses.append((200, reply("Answer")))
    await agent.run("Hi", [])
    assert "tools" not in requests[0][1]
    assert "DATA" in requests[0][1]["messages"][0]["content"]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.ConnectError("refused"), "could not be reached"),
        ((404, {"error": "model not found"}), "ollama pull qwen3:8b"),
        ((500, {"error": "SECRET"}), "server failed"),
        ((400, {"error": "SECRET"}), "rejected the request"),
        ((200, reply("cut", finish="length")), "ran out of output tokens"),
    ],
)
async def test_safe_errors(agent, server, response, message):
    server[0].append(response)
    with pytest.raises(ResearchFailure, match=message) as error:
        await agent.run("AAPL price?", [])
    assert "SECRET" not in str(error.value)


async def test_local_json_parses_and_never_raises(server, monkeypatch):
    responses, requests = server
    responses.append((200, reply('<think>x</think>{"kind": "lookup"}')))
    assert await local_json("system", "prompt") == ({"kind": "lookup"}, 50, 20)
    assert requests[0][1]["response_format"] == {"type": "json_object"}
    responses.append((200, reply('Sure:\n```json\n{"kind": "news"}\n```')))
    assert (await local_json("system", "prompt"))[0] == {"kind": "news"}
    responses.append((200, reply("not json")))
    assert await local_json("system", "prompt") == (None, 0, 0)
    responses.append(httpx.ConnectError("refused"))
    assert await local_json("system", "prompt") == (None, 0, 0)
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "")
    assert await local_json("system", "prompt") == (None, 0, 0)
    assert len(requests) == 4


async def test_empty_key_sends_no_auth_header_and_thinking_toggle(agent, server, monkeypatch):
    responses, requests = server
    seen = []
    original = module.httpx.AsyncClient

    def capture(**kwargs):
        client = original(**kwargs)

        async def record(request):
            seen.append(request.headers)

        client.event_hooks["request"].append(record)
        return client

    monkeypatch.setattr(module.httpx, "AsyncClient", capture)
    monkeypatch.setattr(settings, "LOCAL_LLM_API_KEY", "")
    responses.append((200, reply("Answer")))
    responses.append((200, reply('{"kind": "lookup"}')))
    await agent.run("Hi", [])
    await local_json("system", "prompt")
    assert all("authorization" not in headers for headers in seen)
    assert requests[0][1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert requests[1][1]["chat_template_kwargs"] == {"enable_thinking": False}
    monkeypatch.setattr(settings, "LOCAL_LLM_THINKING", True)
    responses.append((200, reply("Answer")))
    await agent.run("Hi", [])
    assert requests[2][1]["chat_template_kwargs"] == {"enable_thinking": True}


async def test_thinking_only_output_explains_budget(agent, server):
    response = reply(None, finish="length")
    response["choices"][0]["message"]["reasoning"] = "Thinking Process: ..."
    server[0].append((200, response))
    with pytest.raises(ResearchFailure, match="LOCAL_LLM_THINKING"):
        await agent.run("AAPL price?", [])
