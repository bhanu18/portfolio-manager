"""Research provider and agent tests are deterministic and never call paid APIs."""

from datetime import UTC, datetime

import pytest

from models.research import ResearchSubmit
from service.research.providers import number, parse_treasury, safe_url, stock_snapshot_sync


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
