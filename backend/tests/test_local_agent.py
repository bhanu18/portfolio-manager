"""Local models on LangChain, end to end through the real ChatOpenAI client.

The OpenAI-compatible server (Ollama, LM Studio, vLLM, mlx_lm) is mocked at the HTTP transport.
Deterministic; never reaches a model server.
"""

import json

import httpx2
import pytest

from core.config import settings
from models.research import MarketSnapshot
from service.research import agent as agent_module
from service.research import models
from service.research.errors import ProviderUnavailable, ResearchFailure
from service.research.langchain_agent import LangChainLocalAgent
from service.research.local_agent import local_json


@pytest.fixture(autouse=True)
def local_settings(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://ollama.test/v1/")
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setattr(settings, "LOCAL_LLM_API_KEY", "ollama")
    monkeypatch.setattr(settings, "LOCAL_LLM_THINKING", False)


@pytest.fixture
def server(monkeypatch):
    requests: list[tuple[str, dict, dict]] = []
    responses: list = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append((str(request.url), json.loads(request.content), dict(request.headers)))
        assert responses, "Unexpected local model request"
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, data = response
        return httpx2.Response(status, json=data)

    monkeypatch.setattr(models, "local_transport", lambda: httpx2.MockTransport(handle))
    return responses, requests


@pytest.fixture
def stages():
    return []


@pytest.fixture
def agent(stages):
    async def progress(**values):
        stages.append(values["stage"])

    return LangChainLocalAgent(progress)


def reply(content="", tool_calls=None, finish="stop"):
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl",
        "object": "chat.completion",
        "created": 1,
        "model": "qwen3:8b",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
    }


def call(call_id, name, **arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


async def test_tool_loop_strips_thinking_and_counts_usage(agent, server, monkeypatch, stages):
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
    responses.append(
        (
            200,
            reply(
                tool_calls=[call("call_1", "stock_snapshot", symbol="AAPL")], finish="tool_calls"
            ),
        )
    )
    responses.append((200, reply("<think>plan</think>\n## Summary\nAAPL at 100.")))
    report = await agent.run("AAPL price?", [])
    assert report == "## Summary\nAAPL at 100."
    url, first, headers = requests[0]
    assert url == "http://ollama.test/v1/chat/completions"
    assert first["model"] == "qwen3:8b"
    assert first["messages"][0]["role"] == "system"
    assert "Web search is unavailable" in first["messages"][0]["content"]
    assert {tool["function"]["name"] for tool in first["tools"]} == {
        "stock_snapshot",
        "investment_analysis",
        "treasury_snapshot",
    }
    # Local servers read `max_tokens`; the thinking toggle rides in the same body.
    assert first["max_tokens"] == 4000 and "max_completion_tokens" not in first
    assert first["chat_template_kwargs"] == {"enable_thinking": False}
    assert headers["authorization"] == "Bearer ollama"
    tool_message = requests[1][1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_1"
    assert json.loads(tool_message["content"])["symbol"] == "AAPL"
    assert (agent.input_tokens, agent.output_tokens, agent.tool_calls) == (100, 40, 1)
    assert agent.evidence[0]["title"] == "AAPL"
    assert stages[0] == "Drafting analysis with the local model"


async def test_restricted_tools_omit_tool_list(server):
    responses, requests = server

    async def progress(**values):
        pass

    agent = LangChainLocalAgent(progress, allowed_tools=set(), extra_instructions="DATA")
    responses.append((200, reply("Answer")))
    report = await agent.run("Hi", [])
    assert "tools" not in requests[0][1]
    assert "DATA" in requests[0][1]["messages"][0]["content"]
    assert report.startswith("No external evidence was retrieved")


@pytest.mark.parametrize(
    ("response", "message", "cooldown"),
    [
        (httpx2.ConnectError("refused"), "could not be reached", 60),
        (httpx2.ReadTimeout("slow"), "took too long", 60),
        ((404, {"error": "model not found"}), "ollama pull qwen3:8b", 300),
        ((500, {"error": "SECRET"}), "server failed", 60),
        ((400, {"error": "SECRET"}), "rejected the request", None),
        ((200, reply("cut", finish="length")), "ran out of output tokens", None),
    ],
)
async def test_safe_errors(agent, server, response, message, cooldown):
    server[0].append(response)
    with pytest.raises(ResearchFailure, match=message) as error:
        await agent.run("AAPL price?", [])
    assert "SECRET" not in str(error.value)
    assert getattr(error.value, "cooldown", None) == cooldown
    assert isinstance(error.value, ProviderUnavailable) is (cooldown is not None)


async def test_thinking_only_output_explains_budget(agent, server):
    server[0].append((200, reply(None, finish="length")))
    with pytest.raises(ResearchFailure, match="LOCAL_LLM_THINKING"):
        await agent.run("AAPL price?", [])
    server[0].append((200, reply("<think>only thoughts</think>")))
    with pytest.raises(ResearchFailure, match="LOCAL_LLM_THINKING"):
        await agent.run("AAPL price?", [])


async def test_thinking_toggle_and_placeholder_key(agent, server, monkeypatch):
    responses, requests = server
    monkeypatch.setattr(settings, "LOCAL_LLM_API_KEY", "")
    monkeypatch.setattr(settings, "LOCAL_LLM_THINKING", True)
    responses.append((200, reply("Answer")))
    await agent.run("Hi", [])
    _, body, headers = requests[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    # The OpenAI client needs some key; local servers ignore this placeholder.
    assert headers["authorization"] == "Bearer unused"


async def test_tool_budget(agent, server, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MAX_TOOL_CALLS", 1)
    calls = [call("a", "stock_snapshot", symbol="A"), call("b", "stock_snapshot", symbol="B")]
    server[0].append((200, reply(tool_calls=calls, finish="tool_calls")))
    with pytest.raises(ResearchFailure, match="tool-call budget"):
        await agent.run("Compare", [])
    assert len(server[1]) == 1


async def test_local_json_parses_and_never_raises(server, monkeypatch):
    responses, requests = server
    responses.append((200, reply('<think>x</think>{"kind": "lookup"}')))
    assert await local_json("system", "prompt") == ({"kind": "lookup"}, 50, 20)
    body = requests[0][1]
    assert body["response_format"] == {"type": "json_object"}
    assert (body["temperature"], body["max_tokens"]) == (0, 300)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    responses.append((200, reply('Sure:\n```json\n{"kind": "news"}\n```')))
    assert (await local_json("system", "prompt"))[0] == {"kind": "news"}
    responses.append((200, reply("not json")))
    assert await local_json("system", "prompt") == (None, 0, 0)
    responses.append(httpx2.ConnectError("refused"))
    assert await local_json("system", "prompt") == (None, 0, 0)
    responses.append((500, {"error": "down"}))
    assert await local_json("system", "prompt") == (None, 0, 0)
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "")
    assert await local_json("system", "prompt") == (None, 0, 0)
    assert len(requests) == 5


async def test_object_tool_arguments_are_accepted(agent, server, monkeypatch):
    """Some servers send `arguments` as an object; the transport shim re-encodes it."""
    responses, _ = server

    async def market(symbol):
        return MarketSnapshot(
            kind="stock_etf",
            symbol=symbol,
            retrieved_at="2026-10-08T00:00:00+00:00",
            source_url="https://example.com/market",
            values={"price": 100},
        )

    monkeypatch.setattr(agent_module, "stock_snapshot", market)
    raw = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "stock_snapshot", "arguments": {"symbol": "AAPL"}},
    }
    responses.append((200, reply(tool_calls=[raw], finish="tool_calls")))
    responses.append((200, reply("AAPL at 100.")))
    assert await agent.run("AAPL price?", []) == "AAPL at 100."
    assert agent.evidence[0]["title"] == "AAPL"
