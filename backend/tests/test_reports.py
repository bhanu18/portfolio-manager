"""Reports API: holding valuation and portfolio performance.

Every network lookup in routers/reports.py goes through a module-level
`_blocking_*` function (plus `calculate_performance_scores`). The `market`
fixture replaces them with a deterministic fake, so these tests never call
Yahoo or the FX provider and the expected numbers can be worked out by hand.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import pandas as pd
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db import orm_models, service
from routers import reports

# Naive on purpose, like the trade_date column (see tests/test_trades.py).
CREATED = datetime(2025, 1, 1)  # noqa: DTZ001


@dataclass
class FakeMarket:
    """What the patched lookups return. Tests edit the fields they care about."""

    # (from, to) -> current rate; a missing pair means the provider has no rate.
    rates: dict[tuple[str, str], float | None] = field(default_factory=dict)
    # (from, to) -> rate at the trade date
    historical: dict[tuple[str, str], float] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
    # symbol -> currency; None means the lookup failed. Unlisted symbols are USD.
    currencies: dict[str, str | None] = field(default_factory=dict)
    benchmark_return: float | None = 10.0
    scoring_error: Exception | None = None

    def rate(self, from_currency: str, to_currency: str) -> float | None:
        if from_currency == to_currency:
            return 1.0
        return self.rates.get((from_currency, to_currency))

    def historical_fx(
        self, from_currency: str, to_currency: str, date: datetime, now: datetime
    ) -> dict[str, Any]:
        rate = (
            1.0
            if from_currency == to_currency
            else self.historical.get((from_currency, to_currency), 1.0)
        )
        return {
            "rate": rate,
            "actual_date": date.strftime("%Y-%m-%d"),
            "source": "fake",
            "warning": None,
        }

    def scores(self, holdings: list, *args: Any) -> dict[str, Any]:
        if self.scoring_error:
            raise self.scoring_error
        return {"portfolio_score": None, "holdings_scores": [], "warnings": []}


@pytest.fixture
def market(monkeypatch: pytest.MonkeyPatch) -> FakeMarket:
    fake = FakeMarket()
    monkeypatch.setattr(reports, "_blocking_rate", fake.rate)
    monkeypatch.setattr(reports, "_blocking_historical_fx", fake.historical_fx)
    monkeypatch.setattr(reports, "_blocking_current_price", lambda s: fake.prices.get(s, 0.0))
    monkeypatch.setattr(
        reports, "_blocking_asset_currency", lambda s: fake.currencies.get(s, "USD")
    )
    monkeypatch.setattr(reports, "_blocking_benchmark_return", lambda *_args: fake.benchmark_return)
    monkeypatch.setattr(reports, "calculate_performance_scores", fake.scores)
    return fake


# ---- Data helpers ----


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/register", json={"name": email.split("@")[0], "email": email, "password": "password123"}
    )
    response = await client.post(
        "/login/access-token", data={"username": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _group(db_session: AsyncSession, name: str, member_email: str | None = None) -> int:
    group = orm_models.Group(name=name)
    db_session.add(group)
    await db_session.flush()
    group_id = group.id
    if member_email:
        user = await service.get_user_by_email(db_session, email=member_email)
        db_session.add(
            orm_models.UserGroupAssociation(
                user_id=user.id, group_id=group_id, role=orm_models.GroupMemberRole.MEMBER
            )
        )
    await db_session.commit()
    db_session.expire_all()  # so the next request reloads the user's groups
    return group_id


async def _asset(
    db_session: AsyncSession,
    symbol: str,
    *,
    current_price: float | None,
    market: str = "NASDAQ",
    type: str = "stock",
) -> int:
    asset = orm_models.Asset(
        symbol=symbol,
        name=f"{symbol} Inc.",
        market=market,
        type=type,
        current_price=current_price,
        created_at=CREATED,
        updated_at=CREATED,
    )
    db_session.add(asset)
    await db_session.commit()
    return asset.id


async def _trade(
    db_session: AsyncSession,
    group_id: int,
    asset_id: int,
    trade_type: str,
    date: str,
    quantity: float,
    price: float,
    currency: str = "USD",
) -> None:
    db_session.add(
        orm_models.Trade(
            asset_id=asset_id,
            group_id=group_id,
            trade_type=trade_type,
            trade_date=datetime.fromisoformat(date),
            quantity=quantity,
            price_per_unit=price,
            currency=currency,
        )
    )
    await db_session.commit()


@pytest.fixture
async def headers(client: AsyncClient) -> dict[str, str]:
    return await _login(client, "owner@example.com")


@pytest.fixture
async def group_id(db_session: AsyncSession, headers: dict[str, str]) -> int:
    """A group the `headers` user belongs to."""
    return await _group(db_session, "Mine", member_email="owner@example.com")


# ---- GET /reports/valuation/{symbol}/{target_currency} ----


async def test_valuation_unknown_asset(client, headers, group_id, market):
    response = await client.get("/reports/valuation/NOPE/USD", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Asset not found"


async def test_valuation_ignores_other_groups_trades(client, db_session, headers, group_id, market):
    other_group = await _group(db_session, "Not mine")
    asset = await _asset(db_session, "AAPL", current_price=200)
    await _trade(db_session, other_group, asset, "buy", "2025-03-01", 10, 100)

    response = await client.get("/reports/valuation/AAPL/USD", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "No trades found for this asset"


async def test_valuation_nets_buys_and_sells(client, db_session, headers, group_id, market):
    market.rates[("USD", "THB")] = 35.0
    asset = await _asset(db_session, "AAPL", current_price=200)
    await _trade(db_session, group_id, asset, "buy", "2025-03-01", 10, 100)
    await _trade(db_session, group_id, asset, "sell", "2025-04-01", 4, 150)

    response = await client.get("/reports/valuation/aapl/thb", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["reporting_currency"] == "THB"
    assert body["asset_native_currency"] == "USD"
    # Cost is net of the sale: 10 * 100 - 4 * 150 = 400 for 6 units.
    assert body["holdings"] == {"quantity": 6, "average_cost_usd": 66.6667}
    assert body["valuation"] == {
        "current_value_native": 1200,
        "current_value_usd": 1200,
        "current_value_in_target_currency": 42000,
    }
    assert body["performance"] == {
        "total_cost_in_target_currency": 14000,
        "profit_loss_in_target_currency": 28000,
    }


async def test_valuation_converts_each_trade_currency(
    client, db_session, headers, group_id, market
):
    market.rates[("EUR", "USD")] = 1.1
    asset = await _asset(db_session, "ASML", current_price=100)
    await _trade(db_session, group_id, asset, "buy", "2025-03-01", 10, 100, currency="EUR")
    await _trade(db_session, group_id, asset, "buy", "2025-04-01", 10, 100)

    response = await client.get("/reports/valuation/ASML/USD", headers=headers)

    assert response.status_code == 200
    # 10 * 100 * 1.1 + 10 * 100 = 2100 USD for 20 units.
    assert response.json()["holdings"] == {"quantity": 20, "average_cost_usd": 105}


async def test_valuation_fully_sold(client, db_session, headers, group_id, market):
    asset = await _asset(db_session, "AAPL", current_price=200)
    await _trade(db_session, group_id, asset, "buy", "2025-03-01", 10, 100)
    await _trade(db_session, group_id, asset, "sell", "2025-04-01", 10, 150)

    response = await client.get("/reports/valuation/AAPL/USD", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message": "No active holdings for this asset."}


async def test_valuation_missing_fx_rate_is_503(client, db_session, headers, group_id, market):
    asset = await _asset(db_session, "ASML", current_price=100)
    await _trade(db_session, group_id, asset, "buy", "2025-03-01", 10, 100, currency="EUR")

    response = await client.get("/reports/valuation/ASML/USD", headers=headers)

    assert response.status_code == 503
    assert "EUR" in response.json()["detail"]


async def test_valuation_falls_back_to_market_currency(
    client, db_session, headers, group_id, market
):
    market.currencies["PTT"] = None  # the yfinance lookup failed
    market.rates[("THB", "USD")] = 0.03
    asset = await _asset(db_session, "PTT", current_price=40, market="SET")
    await _trade(db_session, group_id, asset, "buy", "2025-03-01", 100, 1)

    response = await client.get("/reports/valuation/PTT/USD", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["asset_native_currency"] == "THB"
    assert body["valuation"]["current_value_native"] == 4000
    assert body["valuation"]["current_value_usd"] == 120


# ---- GET /reports/portfolio-performance ----


async def _performance(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/reports/portfolio-performance", headers=headers)
    assert response.status_code == 200
    return response.json()


async def test_performance_empty_portfolio(client, headers, group_id, market):
    body = await _performance(client, headers)

    assert body["holdings"] == []
    assert body["portfolio_summary"]["total_cost_basis"] == 0
    assert body["portfolio_summary"]["total_current_value"] == 0
    assert body["portfolio_summary"]["total_unrealized_gain_loss_pct"] == 0
    assert body["portfolio_summary"]["benchmark_return"] == 0
    assert body["by_currency"] == {}


@pytest.mark.parametrize(
    ("sold", "quantity", "cost_basis", "purchase_date"),
    [
        # Sell 5: the oldest lot keeps 5 @ 100, the newer lot stays whole (10 @ 120).
        (5, 15, 5 * 100 + 10 * 120, "2025-01-10"),
        # Sell 12: the oldest lot is gone, 8 @ 120 remain, so the holding dates from June.
        (12, 8, 8 * 120, "2025-06-10"),
    ],
)
async def test_performance_cost_basis_is_fifo(
    client, db_session, headers, group_id, market, sold, quantity, cost_basis, purchase_date
):
    asset = await _asset(db_session, "AAPL", current_price=150)
    await _trade(db_session, group_id, asset, "buy", "2025-01-10", 10, 100)
    await _trade(db_session, group_id, asset, "buy", "2025-06-10", 10, 120)
    await _trade(db_session, group_id, asset, "sell", "2025-09-01", sold, 130)

    body = await _performance(client, headers)

    [holding] = body["holdings"]
    assert holding["quantity"] == quantity
    assert holding["cost_basis_base"] == cost_basis
    assert holding["purchase_price_original"] == round(cost_basis / quantity, 2)
    assert holding["purchase_date"] == purchase_date
    assert holding["current_value_base"] == quantity * 150
    assert holding["weight_pct"] == 100
    assert body["portfolio_summary"]["total_cost_basis"] == cost_basis


async def test_performance_splits_local_and_fx_return(
    client, db_session, headers, group_id, market
):
    market.historical[("EUR", "USD")] = 1.0
    market.rates[("EUR", "USD")] = 1.2
    asml = await _asset(db_session, "ASML", current_price=110)
    aapl = await _asset(db_session, "AAPL", current_price=100)
    await _trade(db_session, group_id, asml, "buy", "2025-03-01", 10, 100, currency="EUR")
    await _trade(db_session, group_id, aapl, "buy", "2025-03-01", 10, 100)

    body = await _performance(client, headers)

    # ASML: cost 1000 USD at the 1.0 purchase rate, now 10 * 110 * 1.2 = 1320 USD.
    # 10% from the price, 20% from the currency.
    assert body["by_currency"]["EUR"] == {
        "value_base": 1320,
        "cost_basis_base": 1000,
        "weight_pct": round(1320 / 2320 * 100, 2),
        "local_return_pct": 10,
        "fx_return_pct": 20,
        "total_return_pct": 32,
    }
    assert body["by_currency"]["USD"]["value_base"] == 1000
    assert body["portfolio_summary"]["total_current_value"] == 2320
    assert body["portfolio_summary"]["currency_impact_summary"]["total_fx_gain_loss"] == 200
    assert body["exchange_rates_current"] == {"USD": 1.0, "EUR": 1.2}
    assert body["top_performers"][0] == {"ticker": "ASML", "total_return_pct": 32}


async def test_performance_warns_when_current_fx_missing(
    client, db_session, headers, group_id, market
):
    asset = await _asset(db_session, "ASML", current_price=110)
    await _trade(db_session, group_id, asset, "buy", "2025-03-01", 10, 100, currency="EUR")

    body = await _performance(client, headers)

    assert body["exchange_rates_current"]["EUR"] == 1.0
    assert {"ticker": "EUR", "message": "Current FX rate EUR->USD unavailable, using 1.0"} in body[
        "fx_warnings"
    ]


async def test_performance_fetches_missing_prices(client, db_session, headers, group_id, market):
    market.prices["MSFT"] = 50
    priced = await _asset(db_session, "MSFT", current_price=None)
    unpriced = await _asset(db_session, "GONE", current_price=None)
    await _trade(db_session, group_id, priced, "buy", "2025-03-01", 2, 40)
    await _trade(db_session, group_id, unpriced, "buy", "2025-03-01", 2, 40)

    body = await _performance(client, headers)

    # MSFT uses the fetched price; GONE has none anywhere and is left out.
    [holding] = body["holdings"]
    assert holding["ticker"] == "MSFT"
    assert holding["current_price_original"] == 50


async def test_performance_survives_scoring_failure(client, db_session, headers, group_id, market):
    market.scoring_error = RuntimeError("no history")
    asset = await _asset(db_session, "AAPL", current_price=150)
    await _trade(db_session, group_id, asset, "buy", "2025-03-01", 1, 100)

    body = await _performance(client, headers)

    assert body["portfolio_score"] is None
    assert body["scoring_warnings"] == [{"ticker": None, "message": "Scoring failed: no history"}]
    assert body["holdings"][0]["score"] is None


async def test_performance_ignores_other_groups(client, db_session, headers, group_id, market):
    other_group = await _group(db_session, "Not mine")
    mine = await _asset(db_session, "AAPL", current_price=150)
    theirs = await _asset(db_session, "TSLA", current_price=150)
    await _trade(db_session, group_id, mine, "buy", "2025-03-01", 1, 100)
    await _trade(db_session, other_group, theirs, "buy", "2025-03-01", 1, 100)

    body = await _performance(client, headers)

    assert [h["ticker"] for h in body["holdings"]] == ["AAPL"]


async def test_reports_require_login(client):
    assert (await client.get("/reports/portfolio-performance")).status_code == 401
    assert (await client.get("/reports/valuation/AAPL/USD")).status_code == 401


# ---- Pure helpers (no database) ----


def _index(*days: str, tz: str | None = "America/New_York") -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(day) for day in days]).tz_localize(tz)


def test_nearest_row_label_uses_last_row_before_a_gap():
    index = _index("2026-01-09", "2026-01-12")  # Friday, Monday
    sunday = datetime(2026, 1, 11)  # noqa: DTZ001 - naive, as it comes out of MySQL

    assert reports._nearest_row_label(index, sunday) == index[0]


def test_nearest_row_label_falls_back_to_first_row():
    index = _index("2026-01-09", "2026-01-12")
    assert reports._nearest_row_label(index, datetime(2026, 1, 1)) == index[0]  # noqa: DTZ001


def test_nearest_row_label_with_naive_index_and_aware_date():
    index = _index("2026-01-09", "2026-01-12", tz=None)
    aware = pd.Timestamp("2026-01-12", tz="UTC").to_pydatetime()

    assert reports._nearest_row_label(index, aware) == index[1]


class _FakeTicker:
    """Stands in for yf.Ticker: history() returns whatever `closes` has for the pair."""

    closes: ClassVar[dict[str, list[tuple[str, float]]]] = {}

    def __init__(self, pair: str):
        self.pair = pair

    def history(self, **_kwargs: Any) -> pd.DataFrame:
        rows = self.closes.get(self.pair, [])
        return pd.DataFrame(
            {"Close": [close for _, close in rows]},
            index=_index(*(day for day, _ in rows)) if rows else pd.DatetimeIndex([]),
        )


@pytest.fixture
def fake_ticker(monkeypatch: pytest.MonkeyPatch) -> type[_FakeTicker]:
    _FakeTicker.closes = {}
    monkeypatch.setattr(reports.yf, "Ticker", _FakeTicker)
    return _FakeTicker


TRADE_DAY = datetime(2026, 1, 12)  # noqa: DTZ001
NOW = datetime(2026, 2, 1)  # noqa: DTZ001


def test_historical_fx_same_currency(fake_ticker):
    result = reports._blocking_historical_fx("USD", "USD", TRADE_DAY, NOW)
    assert (result["rate"], result["source"]) == (1.0, "same_currency")


def test_historical_fx_direct_pair(fake_ticker):
    fake_ticker.closes["EURUSD=X"] = [("2026-01-12", 1.1)]

    result = reports._blocking_historical_fx("EUR", "USD", TRADE_DAY, NOW)

    assert result == {
        "rate": 1.1,
        "actual_date": "2026-01-12",
        "source": "yfinance",
        "warning": None,
    }


def test_historical_fx_inverse_pair_with_nearest_date(fake_ticker):
    fake_ticker.closes["USDEUR=X"] = [("2026-01-09", 0.8)]

    result = reports._blocking_historical_fx("EUR", "USD", TRADE_DAY, NOW)

    assert result["rate"] == pytest.approx(1.25)
    assert result["source"] == "yfinance_inverse"
    assert result["warning"] == "Used 2026-01-09 (nearest to 2026-01-12)"


def test_historical_fx_falls_back_to_current_rate(fake_ticker, monkeypatch):
    monkeypatch.setattr(reports, "_blocking_rate", lambda *_args: 0.9)

    result = reports._blocking_historical_fx("EUR", "USD", TRADE_DAY, NOW)

    assert (result["rate"], result["source"]) == (0.9, "fallback_current")
    assert result["actual_date"] == "2026-02-01"


def test_historical_fx_falls_back_to_one(fake_ticker, monkeypatch):
    monkeypatch.setattr(reports, "_blocking_rate", lambda *_args: None)

    result = reports._blocking_historical_fx("EUR", "USD", TRADE_DAY, NOW)

    assert (result["rate"], result["source"]) == (1.0, "fallback_default")
