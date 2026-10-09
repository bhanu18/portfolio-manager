"""Model-assisted column mapping for exports that don't match a known broker layout.

The local model only names which column holds which field; every value is still parsed
by the deterministic helpers in ``base``. Only the headers and a few sample rows are
sent, and only to the locally configured model.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import pandas as pd

from core.config import settings
from service.imports.base import (
    ParseError,
    TradeRow,
    normalize_side,
    parse_date,
    require_columns,
    skipped_row,
    to_float,
)
from service.research.local_agent import local_json

REQUIRED_FIELDS = ("symbol", "trade_date", "quantity", "price")
OPTIONAL_FIELDS = ("side", "fee", "currency", "broker_ref")
SAMPLE_ROWS = 5

SYSTEM = (
    "You map the columns of a stock trade export onto a fixed schema. Reply with one JSON "
    "object whose keys are: " + ", ".join(REQUIRED_FIELDS + OPTIONAL_FIELDS) + ". Each value "
    "must be one of the file's column names copied exactly, or null when no column fits. "
    "symbol = ticker; trade_date = when the trade happened (not today's/quote date); "
    "quantity = units traded; price = price per unit paid or received (not current price); "
    "side = buy/sell column; fee = commission; currency = currency code; broker_ref = order "
    "or transaction id. Do not invent column names."
)


@dataclass
class ColumnMapping:
    symbol: str
    trade_date: str
    quantity: str
    price: str
    side: str | None = None
    fee: str | None = None
    currency: str | None = None
    broker_ref: str | None = None

    def as_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value}


def validate_mapping(data: object, columns: Iterable[str]) -> ColumnMapping | None:
    """Accept a model reply only if every named column really exists in the file."""
    if not isinstance(data, dict):
        return None
    present = {str(c) for c in columns}
    fields: dict[str, str | None] = {}
    for key in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        value = data.get(key)
        if value in (None, ""):
            fields[key] = None
            continue
        if not isinstance(value, str) or value not in present:
            return None  # a column the file doesn't have: don't trust any of the reply
        fields[key] = value
    if any(fields[key] is None for key in REQUIRED_FIELDS):
        return None
    return ColumnMapping(**fields)  # type: ignore[arg-type]


async def infer_mapping(df: pd.DataFrame) -> ColumnMapping | None:
    """Ask the local model which column is which. None when unavailable or untrustworthy."""
    if df.empty:
        return None
    prompt = (
        "Columns: "
        + ", ".join(repr(str(c)) for c in df.columns)
        + "\n\nFirst rows:\n"
        + df.head(SAMPLE_ROWS).to_csv(index=False)
    )
    data, _, _ = await local_json(
        SYSTEM, prompt, max_tokens=500, model=settings.IMPORT_LLM_MODEL or None
    )
    return validate_mapping(data, df.columns)


class MappedParser:
    code = "mapped"
    label = "Mapped columns"
    ref_prefix = "mapped"

    def __init__(self, mapping: ColumnMapping):
        self.mapping = mapping

    def matches(self, columns: Iterable[str]) -> bool:
        return validate_mapping(self.mapping.as_dict(), columns) is not None

    def parse(self, df: pd.DataFrame) -> list[TradeRow]:
        m = self.mapping
        require_columns(df.columns, m.as_dict().values())

        rows: list[TradeRow] = []
        for position, (_, raw) in enumerate(df.iterrows(), start=2):  # line 1 is the header
            quantity = to_float(raw[m.quantity])
            if m.side:
                side = normalize_side(raw[m.side])
                if side is None:
                    rows.append(skipped_row(position, f"unknown {m.side} {raw[m.side]!r}"))
                    continue
            else:
                # No side column: a signed quantity carries the direction.
                side = "sell" if quantity < 0 else "buy"
            quantity = abs(quantity)

            trade_date = parse_date(
                raw[m.trade_date], formats=("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y")
            )
            if trade_date is None:
                rows.append(skipped_row(position, f"unparseable date {raw[m.trade_date]!r}"))
                continue

            symbol = str(raw[m.symbol]).strip().upper()
            price = to_float(raw[m.price])
            if not symbol or symbol == "NAN" or quantity <= 0 or price <= 0:
                rows.append(skipped_row(position, "missing symbol, quantity or price"))
                continue

            currency = str(raw[m.currency]).strip().upper() if m.currency else ""
            broker_ref = str(raw[m.broker_ref]).strip() if m.broker_ref else ""
            rows.append(
                TradeRow(
                    symbol=symbol,
                    trade_type=side,
                    trade_date=trade_date,
                    quantity=quantity,
                    price_per_unit=price,
                    currency=currency if len(currency) == 3 else "USD",
                    fee=abs(to_float(raw[m.fee])) if m.fee else 0.0,
                    broker_ref=broker_ref if broker_ref and broker_ref != "nan" else None,
                )
            )

        if rows and not any(r.quantity > 0 for r in rows):
            raise ParseError("no usable trades found with the mapped columns")
        return rows
