import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from service.research import agent as agent_module
from service.research.investment import (
    COST,
    analyze,
    investment_snapshot_sync,
    simulate,
)


def dates(n):
    return [day.date().isoformat() for day in pd.bdate_range("2015-01-01", periods=n)]


def test_moving_averages_and_metrics_use_all_observations():
    values = list(range(1, 1201))
    result = analyze(dates(len(values)), values)
    assert result.sma50 == pytest.approx(sum(values[-50:]) / 50)
    assert result.sma200 == pytest.approx(sum(values[-200:]) / 200)
    assert len(result.backtests) == 9
    assert len(result.trend) <= 160
    full = result.backtests[0]
    # First fill is close[200]; all gains after that count.
    expected = (1 - COST) * values[-1] / values[200] - 1
    assert full.total_return == pytest.approx(expected)
    assert full.trades == 1
    assert full.max_drawdown == pytest.approx(-COST)
    assert full.time_invested == pytest.approx(999 / 1000)
    assert full.curve[-1].date == dates(len(values))[-1]


def test_signal_cannot_capture_return_before_execution_and_costs_on_both_sides():
    result = simulate(
        dates(4), [100, 200, 300, 600], [True, False, False, False], 1, 4, "test", "full"
    )
    # Buy at 200 after the first jump; hold 200->300 then exit. Miss 300->600.
    assert result.total_return == pytest.approx((1 - COST) ** 2 * 1.5 - 1)
    assert result.trades == 2
    assert result.time_invested == pytest.approx(1 / 3)
    assert result.annualized_return is None


def test_cash_and_flat_market_and_crossover():
    flat = analyze(dates(260), [100.0] * 260)
    assert flat.backtests[1].total_return == 0
    assert flat.backtests[1].trades == 0
    assert flat.backtests[0].total_return == pytest.approx(-COST)
    assert flat.last_crossover is None
    falling = list(range(600, 300, -1))
    rising = list(range(301, 701))
    result = analyze(dates(700), falling + rising)
    assert result.last_crossover["direction"] == "bullish"
    assert result.backtests[0].max_drawdown < -0.1


@pytest.mark.parametrize("values", [[1.0] * 200, [0.0] * 201, [float("nan")] * 201, [-1.0] * 201])
def test_bad_or_short_history_is_unavailable(values):
    with pytest.raises(ValueError):
        analyze(dates(len(values)), values)


def test_duplicate_or_unsorted_dates_rejected():
    with pytest.raises(ValueError):
        analyze(["2020-01-01"] * 201, [100.0] * 201)


def test_provider_stale_history_and_explicit_adjustments(monkeypatch):
    class Ticker:
        def history(self, **kwargs):
            assert kwargs["auto_adjust"] is True and kwargs["actions"] is False
            assert kwargs["end"] == datetime.now(UTC).date().isoformat()
            return pd.DataFrame(
                {"Close": [100.0] * 260},
                index=pd.bdate_range(
                    end=datetime.now(UTC).date() - pd.Timedelta(days=10), periods=260
                ),
            )

    monkeypatch.setattr("service.research.investment.yf.Ticker", lambda _: Ticker())
    result = investment_snapshot_sync("aapl")
    assert result.symbol == "AAPL"
    assert any("four calendar" in warning for warning in result.warnings)
    assert any("five years" in warning for warning in result.warnings)
    assert result.analysis.sma200 == 100
    assert result.source_url.endswith("/AAPL/history/")


async def test_both_agents_share_calculation_tool_and_persist_charts(monkeypatch):
    from models.research import MarketSnapshot
    from service.research.anthropic_agent import CLIENT_TOOLS, AnthropicResearchAgent

    async def snapshot(symbol):
        return MarketSnapshot(
            kind="investment_analysis",
            symbol=symbol,
            retrieved_at="2026-01-01",
            source_url="https://finance.yahoo.com/quote/AAPL/history/",
            analysis=analyze(dates(260), [100.0] * 260),
        )

    monkeypatch.setattr(agent_module, "investment_snapshot", snapshot)

    async def progress(**kwargs):
        pass

    assert any(tool["name"] == "investment_analysis" for tool in CLIENT_TOOLS)
    for cls in (agent_module.ResearchAgent, AnthropicResearchAgent):
        agent = cls(progress)
        output = json.loads(
            await agent.execute_tool(
                {"name": "investment_analysis", "arguments": '{"symbol":"AAPL"}'}
            )
        )
        assert output["analysis"]["sma200"] == 100
        assert "trend" not in output["analysis"]
        assert "curve" not in output["analysis"]["backtests"][0]
        assert agent.evidence[0]["snapshot"]["analysis"]["backtests"][0]["curve"]


def test_valuation_missing_and_negative_cash_flow(monkeypatch):
    from service.research.providers import stock_snapshot_sync

    class Ticker:
        def get_info(self):
            return {"quoteType": "EQUITY", "marketCap": 1000, "freeCashflow": -50}

    monkeypatch.setattr("service.research.providers.yf.Ticker", lambda _: Ticker())
    snapshot = stock_snapshot_sync("AAPL")
    assert snapshot.values["free_cash_flow_yield"] == -0.05
    assert snapshot.values["forward_pe"] is None
