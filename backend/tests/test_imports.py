"""Parser and pipeline unit tests. No database required."""

import io

import pandas as pd
import pytest

from service.imports import mapping as mapping_module
from service.imports.base import ParseError, TradeRow, make_source_ref, normalize_side, to_float
from service.imports.mapping import MappedParser
from service.imports.pipeline import to_payloads
from service.imports.registry import get_parser, parse_upload, sniff_broker

YAHOO_CSV = """Symbol,Current Price,Date,Trade Date,Purchase Price,Quantity,Commission,High Limit,Transaction Type
NVDA,219.5,2026/09/18,20241206,145.53,2.0,0.51,,SELL
NVDA,219.5,2026/09/18,20241122,142.1,2.0,0.0,,BUY
NFLX,71.9,2026/09/18,20260625,72.715,2.86282,0.22,,BUY
NFLX,71.9,2026/09/18,20260625,72.74,2.21177,0.24,,BUY
BAD,71.9,2026/09/18,20260625,72.74,1.0,0.0,,DIVIDEND
"""


@pytest.fixture
def yahoo_df(tmp_path):
    path = tmp_path / "yahoo.csv"
    path.write_text(YAHOO_CSV)
    return pd.read_csv(path)


def test_sniff_detects_yahoo(yahoo_df):
    assert sniff_broker(yahoo_df).code == "yahoo"


def test_sniff_rejects_unknown_file():
    with pytest.raises(ParseError):
        sniff_broker(pd.DataFrame({"foo": [1], "bar": [2]}))


def test_yahoo_parses_sides_dates_and_fees(yahoo_df):
    rows = [r for r in get_parser("yahoo").parse(yahoo_df) if r.quantity > 0]
    assert len(rows) == 4

    sell = rows[0]
    assert sell.trade_type == "sell"
    assert sell.trade_date.strftime("%Y-%m-%d") == "2024-12-06"
    # Commission reduces the proceeds of a sell.
    assert sell.effective_price() == pytest.approx(145.53 - 0.51 / 2)

    buy = rows[2]
    assert buy.trade_type == "buy"
    # ...and increases the cost of a buy.
    assert buy.effective_price() == pytest.approx(72.715 + 0.22 / 2.86282)


def test_yahoo_reports_unsupported_transaction_type(yahoo_df):
    skipped = [r for r in get_parser("yahoo").parse(yahoo_df) if r.quantity == 0]
    assert len(skipped) == 1
    assert "DIVIDEND" in skipped[0].warnings[0]


def test_same_day_fills_get_distinct_refs(yahoo_df):
    rows = [r for r in get_parser("yahoo").parse(yahoo_df) if r.quantity > 0]
    payloads = to_payloads(rows, "yahoo", group_id=1)
    refs = [p["source_ref"] for p in payloads]
    assert len(set(refs)) == len(refs)


def test_source_ref_is_stable_across_runs(yahoo_df):
    rows = [r for r in get_parser("yahoo").parse(yahoo_df) if r.quantity > 0]
    assert [p["source_ref"] for p in to_payloads(rows, "yahoo", 1)] == [
        p["source_ref"] for p in to_payloads(rows, "yahoo", 1)
    ]


def test_source_ref_differs_by_broker_and_group(yahoo_df):
    rows = [r for r in get_parser("yahoo").parse(yahoo_df) if r.quantity > 0]
    yahoo_refs = {p["source_ref"] for p in to_payloads(rows, "yahoo", 1)}
    other_broker = {p["source_ref"] for p in to_payloads(rows, "dime", 1)}
    other_group = {p["source_ref"] for p in to_payloads(rows, "yahoo", 2)}
    assert not yahoo_refs & other_broker
    assert not yahoo_refs & other_group


def test_broker_ref_wins_over_position():
    row = TradeRow(
        symbol="NVDA",
        trade_type="buy",
        trade_date=pd.Timestamp("2026-01-02").to_pydatetime(),
        quantity=1,
        price_per_unit=100,
        broker_ref="ORDER-123",
    )
    # Same broker ref at a different position in the file -> same id.
    assert make_source_ref("dime", 1, row, 0) == make_source_ref("dime", 1, row, 5)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("BUY", "buy"), ("Sold", "sell"), ("b", "buy"), ("dividend", None)],
)
def test_normalize_side(raw, expected):
    assert normalize_side(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234.5", 1234.5), ("$12.30", 12.3), ("(4.5)", -4.5), ("--", 0.0), (None, 0.0)],
)
def test_to_float_handles_broker_formatting(raw, expected):
    assert to_float(raw) == expected


# --- model-assisted column mapping -------------------------------------------------

RENAMED_CSV = """Ticker,Date,Shares,Price,Action,Fees
nvda,2024-12-06,2,145.53,Sold,0.51
NFLX,2026-06-25,2.86282,72.715,Bought,0.22
"""

SIGNED_CSV = """Ticker,Date,Shares,Price
AAPL,2026-01-02,5,190
AAPL,2026-02-03,-2,210
"""

RENAMED_MAPPING = {
    "symbol": "Ticker",
    "trade_date": "Date",
    "quantity": "Shares",
    "price": "Price",
    "side": "Action",
    "fee": "Fees",
    "currency": None,
    "broker_ref": None,
}


def _df(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text))


def _fake_model(monkeypatch, reply):
    calls = []

    async def fake_local_json(system, prompt, *, max_tokens=300, model=None):
        calls.append(prompt)
        return reply, 0, 0

    monkeypatch.setattr(mapping_module, "local_json", fake_local_json)
    return calls


def test_mapped_parser_reads_renamed_columns():
    mapping = mapping_module.validate_mapping(RENAMED_MAPPING, _df(RENAMED_CSV).columns)
    rows = MappedParser(mapping).parse(_df(RENAMED_CSV))
    assert [(r.symbol, r.trade_type, r.quantity) for r in rows] == [
        ("NVDA", "sell", 2.0),
        ("NFLX", "buy", 2.86282),
    ]
    assert rows[0].trade_date.strftime("%Y-%m-%d") == "2024-12-06"
    assert rows[0].effective_price() == pytest.approx(145.53 - 0.51 / 2)


def test_mapped_parser_uses_sign_when_there_is_no_side_column():
    mapping = mapping_module.ColumnMapping(
        symbol="Ticker", trade_date="Date", quantity="Shares", price="Price"
    )
    rows = MappedParser(mapping).parse(_df(SIGNED_CSV))
    assert [(r.trade_type, r.quantity) for r in rows] == [("buy", 5.0), ("sell", 2.0)]


async def test_infer_mapping_accepts_valid_reply(monkeypatch):
    calls = _fake_model(monkeypatch, RENAMED_MAPPING)
    mapping = await mapping_module.infer_mapping(_df(RENAMED_CSV))
    assert mapping is not None and mapping.side == "Action"
    # Only headers and sample rows are sent.
    assert "Ticker" in calls[0]


async def test_infer_mapping_rejects_invented_column(monkeypatch):
    _fake_model(monkeypatch, {**RENAMED_MAPPING, "price": "Purchase Price"})
    assert await mapping_module.infer_mapping(_df(RENAMED_CSV)) is None


async def test_infer_mapping_rejects_missing_required_field(monkeypatch):
    _fake_model(monkeypatch, {**RENAMED_MAPPING, "quantity": None})
    assert await mapping_module.infer_mapping(_df(RENAMED_CSV)) is None


async def test_infer_mapping_none_without_model(monkeypatch):
    _fake_model(monkeypatch, None)
    assert await mapping_module.infer_mapping(_df(RENAMED_CSV)) is None


async def test_parse_upload_prefers_yahoo_without_calling_model(monkeypatch):
    calls = _fake_model(monkeypatch, RENAMED_MAPPING)
    source, rows, mapping = await parse_upload(YAHOO_CSV.encode(), "portfolio.csv")
    assert source == "yahoo" and mapping is None and not calls
    assert len([r for r in rows if r.quantity > 0]) == 4


async def test_parse_upload_falls_back_to_mapping(monkeypatch):
    _fake_model(monkeypatch, RENAMED_MAPPING)
    source, rows, mapping = await parse_upload(RENAMED_CSV.encode(), "edited.csv")
    assert source == "mapped" and mapping is not None and len(rows) == 2


async def test_parse_upload_explains_unrecognised_file(monkeypatch):
    _fake_model(monkeypatch, None)
    with pytest.raises(ParseError, match="LOCAL_LLM_MODEL"):
        await parse_upload(RENAMED_CSV.encode(), "edited.csv")
