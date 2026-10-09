"""Auto-mode routing tests: fake agents and market data, no network or paid calls."""

from typing import ClassVar

import httpx
import pytest

from core.config import settings
from models.research import Citation, MarketSnapshot
from service.research import orchestrator as module
from service.research.agent import ProviderUnavailable, ResearchAgent, ResearchFailure, http_failure
from service.research.orchestrator import (
    FailoverResearchAgent,
    ResearchOrchestrator,
    TaskProfile,
    candidates,
    heuristic_profile,
    merge_profiles,
)

FAIL: set[str] = set()
OUT_OF_CREDIT: set[str] = set()


class FakeAgent(ResearchAgent):
    runs: ClassVar[list["FakeAgent"]] = []

    async def run(self, prompt, history):
        FakeAgent.runs.append(self)
        self.input_tokens += 100
        self.output_tokens += 10
        self.model_turns += 1
        await self.checkpoint("Working")
        if self.model in OUT_OF_CREDIT:
            raise ProviderUnavailable(f"{self.model} credit exhausted.", cooldown=1800)
        if self.model in FAIL:
            raise ResearchFailure(f"{self.model} failed")
        if self.allowed_tools == {"web_search"}:
            self.add_source("News", "https://news.example.com/a")
            self.citations = [
                Citation(
                    url="https://news.example.com/a", title="News", start_index=0, end_index=4
                ).model_dump()
            ]
            return "- Earnings beat (News, https://news.example.com/a)"
        return f"Report by {self.model}"


@pytest.fixture
def setup(monkeypatch):
    FakeAgent.runs = []
    FAIL.clear()
    OUT_OF_CREDIT.clear()
    module.COOLDOWNS.clear()
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "fake")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setattr(settings, "RESEARCH_TIER_CHEAP", "openai:gpt-5-mini")
    monkeypatch.setattr(settings, "RESEARCH_TIER_STRONG", "anthropic:claude-sonnet-5-5")
    for name in ("openai", "anthropic", "local"):
        monkeypatch.setitem(module.AGENTS, name, FakeAgent)
    classified: list[dict | None] = []
    market_calls: list[str] = []

    async def classifier(system, prompt):
        return (classified.pop(0) if classified else None), 30, 5

    def snapshot(name, kind="stock_etf"):
        async def fetch(arg):
            market_calls.append(f"{name}:{arg}")
            if arg == "BAD":
                raise RuntimeError("upstream payload")
            return MarketSnapshot(
                kind=kind,
                symbol=None if kind == "treasury" else arg,
                retrieved_at="2026-10-08T00:00:00+00:00",
                source_url=f"https://example.com/{name}/{arg}",
                values={"price": 1},
            )

        return fetch

    monkeypatch.setattr(module, "local_json", classifier)
    monkeypatch.setattr(module, "stock_snapshot", snapshot("stock"))
    monkeypatch.setattr(module, "investment_snapshot", snapshot("investment"))
    monkeypatch.setattr(module, "treasury_snapshot", snapshot("treasury", "treasury"))
    events: list[dict] = []

    async def progress(**values):
        events.append(values)

    return ResearchOrchestrator(progress), classified, market_calls, events


def test_heuristics():
    assert heuristic_profile("What is AAPL trading at?").kind == "lookup"
    assert heuristic_profile("What is AAPL trading at?").symbols == ["AAPL"]
    profile = heuristic_profile("Backtest $msft MA50/200 and latest earnings news")
    assert (profile.kind, profile.needs_web, profile.symbols) == ("analysis", True, ["MSFT"])
    assert heuristic_profile("10Y treasury yield curve").treasury
    assert heuristic_profile("hi").kind == "clarify"
    assert heuristic_profile("and the dividend?", "What about KO").symbols == ["KO"]
    # Classifier can only raise the routing floor, never lower it.
    merged = merge_profiles(
        heuristic_profile("Valuation of NVDA"),
        TaskProfile(kind="lookup", symbols=["nvda", "AMD", "not a ticker"]),
    )
    assert (merged.kind, merged.symbols) == ("analysis", ["NVDA", "AMD"])


def test_candidates_fall_back_and_skip_local_for_web(setup, monkeypatch):
    target = [(t.provider, t.model) for t in candidates("local")]
    assert target[0] == ("local", "qwen3:8b")
    assert candidates("cheap", web=True)[0].provider == "openai"
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert [t.provider for t in candidates("local")] == ["anthropic"]
    monkeypatch.setattr(settings, "RESEARCH_TIER_CHEAP", "local:llama3.1:8b")
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "llama3.1:8b")
    assert candidates("cheap")[0].model == "llama3.1:8b"
    assert [t.provider for t in candidates("cheap", web=True)] == ["anthropic"]


async def test_lookup_stays_local_with_prefetched_data(setup):
    orchestrator, classified, market_calls, events = setup
    classified.append({"kind": "lookup", "needs_web": False, "symbols": ["AAPL"]})
    report = await orchestrator.run("AAPL price?", [])
    assert report == "Report by qwen3:8b"
    assert market_calls == ["stock:AAPL"]
    (writer,) = FakeAgent.runs
    assert writer.allowed_tools == set()  # data already fetched; no repeat tool calls
    assert '"symbol": "AAPL"' in writer.extra_instructions
    assert [(s["role"], s["provider"], s["status"]) for s in orchestrator.steps] == [
        ("classify", "local", "completed"),
        ("data", "tools", "completed"),
        ("writer", "local", "completed"),
    ]
    assert orchestrator.model == "auto: qwen3:8b"
    assert (orchestrator.input_tokens, orchestrator.output_tokens) == (130, 15)
    assert events[-1]["steps"][-1]["input_tokens"] == 100
    assert orchestrator.evidence[0]["title"] == "AAPL"


async def test_analysis_with_news_uses_cheap_web_and_strong_writer(setup):
    orchestrator, _, market_calls, _ = setup
    report = await orchestrator.run("Backtest MSFT MA50/200 and latest earnings news", [])
    assert report == "Report by claude-sonnet-5-5"
    assert market_calls == ["stock:MSFT", "investment:MSFT"]
    web, writer = FakeAgent.runs
    assert (web.model, web.allowed_tools, web.output_budget) == ("gpt-5-mini", {"web_search"}, 1500)
    assert "Earnings beat" in writer.extra_instructions
    assert orchestrator.steps[0]["note"].startswith("Classifier unavailable; used rules.")
    assert orchestrator.model == "auto: qwen3:8b→gpt-5-mini→claude-sonnet-5-5"
    # Web citations keep their sources but lose spans that pointed into the notes.
    assert orchestrator.citations == [
        {
            "url": "https://news.example.com/a",
            "title": "News",
            "start_index": None,
            "end_index": None,
        }
    ]
    assert [e["url"] for e in orchestrator.evidence][-1] == "https://news.example.com/a"


async def test_missing_data_lets_writer_use_tools(setup):
    orchestrator, classified, _, _ = setup
    classified.append({"kind": "lookup", "symbols": ["BAD"]})
    await orchestrator.run("BAD quote", [])
    assert FakeAgent.runs[0].allowed_tools == module.READ_TOOLS
    assert "upstream payload" not in FakeAgent.runs[0].extra_instructions
    assert "missing BAD" in orchestrator.steps[1]["note"]


async def test_local_writer_failure_escalates_once(setup):
    orchestrator, _, _, _ = setup
    FAIL.add("qwen3:8b")
    assert await orchestrator.run("AAPL price?", []) == "Report by gpt-5-mini"
    assert [s["status"] for s in orchestrator.steps if s["role"] == "writer"] == [
        "failed",
        "completed",
    ]


async def test_cloud_writer_failure_is_not_retried(setup):
    orchestrator, _, _, _ = setup
    FAIL.add("claude-sonnet-5-5")
    with pytest.raises(ResearchFailure, match="claude-sonnet-5-5 failed"):
        await orchestrator.run("Valuation scenarios for NVDA", [])
    assert [run.model for run in FakeAgent.runs] == ["claude-sonnet-5-5"]


async def test_web_skipped_without_cloud(setup, monkeypatch):
    orchestrator, _, _, _ = setup
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    assert await orchestrator.run("Latest news on the Fed", []) == "Report by qwen3:8b"
    web = next(s for s in orchestrator.steps if s["role"] == "web")
    assert web["status"] == "skipped"
    assert "web research was not retrieved" in FakeAgent.runs[0].extra_instructions


async def test_out_of_credit_writer_fails_over_and_cools_down(setup):
    orchestrator, _, _, _ = setup
    OUT_OF_CREDIT.add("claude-sonnet-5-5")
    assert await orchestrator.run("Valuation scenarios for NVDA", []) == "Report by gpt-5-mini"
    writer = [s for s in orchestrator.steps if s["role"] == "writer"]
    assert [(s["model"], s["status"]) for s in writer] == [
        ("claude-sonnet-5-5", "failed"),
        ("gpt-5-mini", "completed"),
    ]
    assert "Failing over" in writer[0]["note"]
    # Later runs skip the exhausted provider first instead of paying for a failed call.
    assert [t.provider for t in candidates("strong")] == ["openai", "local", "anthropic"]


async def test_out_of_credit_web_step_uses_other_cloud(setup):
    orchestrator, _, _, _ = setup
    OUT_OF_CREDIT.add("gpt-5-mini")
    await orchestrator.run("Latest news on the Fed", [])
    web = [(s["model"], s["status"]) for s in orchestrator.steps if s["role"] == "web"]
    assert web == [("gpt-5-mini", "failed"), ("claude-sonnet-5-5", "completed")]
    assert "Earnings beat" in FakeAgent.runs[-1].extra_instructions


async def test_all_models_unavailable(setup):
    orchestrator, _, _, _ = setup
    OUT_OF_CREDIT.update({"qwen3:8b", "gpt-5-mini", "claude-sonnet-5-5"})
    with pytest.raises(ResearchFailure, match="Every configured research model is unavailable"):
        await orchestrator.run("AAPL price?", [])


@pytest.mark.parametrize(
    ("status", "body", "unavailable", "cooldown"),
    [
        (400, {"error": {"message": "Your credit balance is too low"}}, True, 1800),
        (429, {"error": {"code": "insufficient_quota"}}, True, 1800),
        (429, {"error": "rate limited"}, True, 60),
        (401, {"error": "bad key"}, True, 1800),
        (529, {"error": "overloaded"}, True, 60),
        (400, {"error": "SECRET bad schema"}, False, None),
    ],
)
def test_http_failure_classification(status, body, unavailable, cooldown):
    request = httpx.Request("POST", "https://api.example.com")
    error = httpx.HTTPStatusError(
        "x", request=request, response=httpx.Response(status, json=body, request=request)
    )
    failure = http_failure(error, "Provider")
    assert isinstance(failure, ProviderUnavailable) is unavailable
    assert getattr(failure, "cooldown", None) == cooldown
    assert "SECRET" not in str(failure)


async def test_explicit_provider_runs_alone_when_healthy(setup):
    _, _, market_calls, events = setup

    async def progress(**values):
        events.append(values)

    agent = FailoverResearchAgent(progress, provider="anthropic", model="saved-model")
    assert await agent.run("Valuation of NVDA", []) == "Report by saved-model"
    (run,) = FakeAgent.runs
    assert run.allowed_tools is None and run.extra_instructions == ""  # plain full-tool run
    assert market_calls == []  # no orchestration steps
    assert agent.model == "saved-model"


async def test_explicit_provider_fails_over_on_credit(setup, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MODEL", "gpt-5-mini")

    async def progress(**values):
        pass

    OUT_OF_CREDIT.add("claude-opus")
    agent = FailoverResearchAgent(progress, provider="anthropic", model="claude-opus")
    assert await agent.run("Research Apple", []) == "Report by gpt-5-mini"
    assert agent.model == "claude-opus→gpt-5-mini"
    assert [(s["model"], s["status"]) for s in agent.steps] == [
        ("claude-opus", "failed"),
        ("gpt-5-mini", "completed"),
    ]
    # The next explicit Anthropic run starts on a healthy provider instead.
    FakeAgent.runs.clear()
    again = FailoverResearchAgent(progress, provider="anthropic", model="claude-opus")
    await again.run("Research Apple", [])
    assert FakeAgent.runs[0].model == "gpt-5-mini"


async def test_explicit_provider_does_not_retry_question_failures(setup):
    async def progress(**values):
        pass

    FAIL.add("claude-opus")
    agent = FailoverResearchAgent(progress, provider="anthropic", model="claude-opus")
    with pytest.raises(ResearchFailure, match="claude-opus failed"):
        await agent.run("Research Apple", [])
    assert len(FakeAgent.runs) == 1


async def test_explicit_provider_all_unavailable(setup, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_MODEL", "gpt-5-mini")

    async def progress(**values):
        pass

    OUT_OF_CREDIT.update({"claude-opus", "gpt-5-mini", "qwen3:8b"})
    agent = FailoverResearchAgent(progress, provider="anthropic", model="claude-opus")
    with pytest.raises(ResearchFailure, match="Every configured research model is unavailable"):
        await agent.run("Research Apple", [])
    assert [run.model for run in FakeAgent.runs] == ["claude-opus", "gpt-5-mini", "qwen3:8b"]


def test_usage_by_model_skips_non_model_steps():
    from service.research.usage import usage_by_model

    steps = [
        {"provider": "rules", "model": "heuristics", "status": "completed"},
        {"provider": "local", "model": "qwen3:8b", "status": "completed", "input_tokens": 30},
        {"provider": "tools", "model": "market data", "status": "completed"},
        {"provider": "openai", "model": "gpt-5-mini", "status": "failed", "input_tokens": 5},
        {"provider": "openai", "model": "gpt-5-mini", "status": "completed", "output_tokens": 9},
        {"provider": "rules", "model": "none", "status": "skipped"},
    ]
    assert usage_by_model(steps) == {
        ("local", "qwen3:8b"): {
            "input_tokens": 30,
            "output_tokens": 0,
            "calls": 1,
            "failed_calls": 0,
        },
        ("openai", "gpt-5-mini"): {
            "input_tokens": 5,
            "output_tokens": 9,
            "calls": 2,
            "failed_calls": 1,
        },
    }
