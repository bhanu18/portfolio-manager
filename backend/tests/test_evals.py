"""Eval harness tests: evaluators, fixtures and the local runner. No network or paid calls."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.config import settings
from evals import evaluators as ev
from evals import fixtures
from evals.run_research import (
    full_target,
    load_rows,
    routing_target,
    run_local,
    summarize,
    sync_dataset,
)
from service.research import orchestrator as orchestrator_module
from service.research.agent import ResearchAgent
from service.research.orchestrator import KIND_RANK


def test_dataset_is_well_formed():
    rows = load_rows()
    assert len(rows) >= 30
    for row in rows:
        assert set(row["inputs"]) == {"prompt", "history"}
        label = row["outputs"]
        assert label["kind"] in KIND_RANK
        assert all(symbol == symbol.upper() for symbol in label["symbols"])
        assert isinstance(label["needs_web"], bool) and isinstance(label["treasury"], bool)
    assert {row["outputs"]["kind"] for row in rows} == set(KIND_RANK)


def test_routing_evaluators():
    reference = {"kind": "analysis", "needs_web": False, "symbols": ["MSFT"], "treasury": False}
    outputs = {
        "profile": {
            "kind": "lookup",
            "needs_web": False,
            "symbols": ["MSFT", "E"],
            "treasury": False,
        }
    }
    scores = {r["key"]: r["score"] for r in (e(outputs, reference) for e in ev.ROUTING)}
    assert scores == {
        "kind_match": 0.0,
        "routing_safe": 0.0,
        "needs_web_match": 1.0,
        "symbols_match": 0.0,
        "treasury_match": 1.0,
    }
    # Explicit-provider runs have no routing decision: not applicable, not a failure.
    assert ev.kind_match({"profile": None}, reference)["score"] is None


def test_report_numbers_skip_dates_indicators_and_prompt_figures():
    report = (
        "On 2026-10-14 MSFT closed at $231.50, 12.5% above its MA50 and 3 backtests ran. "
        "Trailing P/E is 24.10 and it fell 0.85 in 2025; see the 10-K."
    )
    found = [text for _, _, text in ev.report_numbers(report, prompt="Is 24.10 cheap?")]
    assert found == ["$231.50", "12.5%", "0.85"]


def test_numbers_grounded_accepts_fractions_shown_as_percent():
    snapshot = fixtures.stock("MSFT").model_dump()
    price = snapshot["values"]["price"]
    margin = snapshot["values"]["profit_margin"]
    outputs = {
        "report": f"Price ${price:.2f}; margin {margin * 100:.1f}%; target $9999.99.",
        "evidence": [{"title": "MSFT", "url": "https://x", "snapshot": snapshot}],
    }
    result = ev.numbers_grounded({"prompt": "MSFT?"}, outputs, {"needs_web": False})
    assert result["score"] == pytest.approx(2 / 3, abs=0.001)
    assert "$9999.99" in result["comment"]
    # Web answers cite pages, not snapshots, so the check does not apply.
    assert ev.numbers_grounded({"prompt": ""}, outputs, {"needs_web": True})["score"] is None


def test_citations_valid():
    report = "Earnings beat."
    good = {"url": "https://news.example.com/a", "title": "A", "start_index": 0, "end_index": 8}
    bad_span = {**good, "end_index": 99}
    unsafe = {**good, "url": "javascript:alert(1)"}
    outputs = {"report": report, "citations": [good, bad_span, unsafe]}
    assert ev.citations_valid(outputs)["score"] == pytest.approx(1 / 3)
    assert ev.citations_valid({"report": report, "citations": []})["score"] is None


def test_fixtures_are_deterministic():
    assert fixtures.stock("aapl") == fixtures.stock("AAPL")
    analysis = fixtures.investment("SPY").analysis
    assert analysis is not None and len(analysis.backtests) == 9  # 3 strategies x 3 periods
    assert fixtures.treasury("curve").values["BC_10YEAR"] == 4.02
    with pytest.raises(ValueError):
        fixtures.stock("ZZZZ")


async def test_offline_market_data_restores_providers():
    original = orchestrator_module.stock_snapshot
    with fixtures.offline_market_data():
        snapshot = await orchestrator_module.stock_snapshot("KO")
        assert snapshot.warnings[0].startswith("Offline eval fixture")
    assert orchestrator_module.stock_snapshot is original


async def test_rules_routing_run():
    rows = load_rows({"lookup-aapl-price", "analysis-backtest", "news-earnings"})
    collected = await run_local(rows, routing_target(rules_only=True), list(ev.ROUTING), 2)
    summary = summarize(collected)
    assert summary["kind_match"] == {"failures": [], "n": 3, "mean": 1.0}


class EchoWriter(ResearchAgent):
    """Writes a report quoting the first prefetched price, like a well-behaved model."""

    async def run(self, prompt, history):
        self.input_tokens, self.output_tokens, self.model_turns = 200, 50, 1
        price = fixtures.stock("MSFT").values["price"]
        return f"MSFT last traded at ${price:.2f}."


async def test_full_offline_run_scores_report(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setitem(orchestrator_module.AGENTS, "local", EchoWriter)

    async def no_classifier(system, prompt):
        return None, 0, 0

    monkeypatch.setattr(orchestrator_module, "local_json", no_classifier)
    rows = load_rows({"lookup-dollar-ticker"})
    with fixtures.offline_market_data():
        (item,) = await run_local(rows, full_target("auto"), [*ev.ROUTING, *ev.REPORT], 1)
    scores = {r["key"]: r["score"] for r in item["results"]}
    assert scores["completed"] == 1.0
    assert scores["numbers_grounded"] == 1.0
    assert scores["total_tokens"] == 250.0
    assert item["outputs"]["writer"] == {"provider": "local", "model": "qwen3:8b"}


def test_sync_dataset_creates_missing_and_updates_changed():
    rows = load_rows()
    first, second = rows[0], rows[1]
    client = MagicMock()
    client.has_dataset.return_value = True
    client.list_examples.return_value = [
        SimpleNamespace(
            id="ex-1",
            metadata={"id": first["id"]},
            inputs=first["inputs"],
            outputs=first["outputs"],
        ),
        SimpleNamespace(
            id="ex-2", metadata={"id": second["id"]}, inputs=second["inputs"], outputs={}
        ),
    ]
    sync_dataset(client, rows)
    client.update_example.assert_called_once_with(
        "ex-2", inputs=second["inputs"], outputs=second["outputs"]
    )
    created = client.create_examples.call_args.kwargs["examples"]
    assert [example["metadata"]["id"] for example in created] == [r["id"] for r in rows[2:]]
