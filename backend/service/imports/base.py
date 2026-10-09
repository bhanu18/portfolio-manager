"""Shared types and helpers for broker trade imports.

A parser's only job is to turn one broker's export into a list of :class:`TradeRow`.
Everything downstream — asset resolution, fee folding, upserting on ``source_ref`` —
is shared, so adding a broker means adding one module, not touching the pipeline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import pandas as pd


@dataclass
class TradeRow:
    """One trade, normalized out of a broker file and not yet resolved to an asset."""

    symbol: str
    trade_type: str  # "buy" | "sell"
    trade_date: datetime
    quantity: float
    price_per_unit: float
    currency: str = "USD"
    fee: float = 0.0
    # Broker's own order/trade id when the export has one. Preferred over the
    # positional fallback because it survives rows being reordered between exports.
    broker_ref: str | None = None
    # Free-form notes the parser wants surfaced to the operator (not stored).
    warnings: list[str] = field(default_factory=list)

    def effective_price(self) -> float:
        """Unit price with the fee folded in: buys cost more, sells net less."""
        if not self.quantity or not self.fee:
            return self.price_per_unit
        per_unit = self.fee / self.quantity
        return (
            self.price_per_unit + per_unit
            if self.trade_type == "buy"
            else self.price_per_unit - per_unit
        )


def skipped_row(line: int, reason: str) -> TradeRow:
    """A placeholder row the pipeline drops, carrying the reason for the operator."""
    return TradeRow(
        symbol="",
        trade_type="buy",
        trade_date=datetime(1970, 1, 1),  # noqa: DTZ001 - sentinel, never stored
        quantity=0.0,
        price_per_unit=0.0,
        warnings=[f"line {line}: {reason}"],
    )


class BrokerParser(Protocol):
    """What every broker module must provide."""

    #: Short identifier used on the command line, e.g. "dime".
    code: str
    #: Human-readable name for logs and the UI.
    label: str
    #: Namespace used inside source_ref. Defaults to ``code``; only differs where an
    #: earlier importer already wrote refs under another name.
    ref_prefix: str

    def matches(self, columns: Iterable[str]) -> bool:
        """True when a file with these column headers belongs to this broker."""
        ...

    def parse(self, df: pd.DataFrame) -> list[TradeRow]:
        """Turn the raw export into normalized trades."""
        ...


class ParseError(Exception):
    """Raised when a file is recognized but cannot be parsed."""


def require_columns(columns: Iterable[str], required: Iterable[str]) -> None:
    present = set(columns)
    missing = [c for c in required if c not in present]
    if missing:
        raise ParseError(f"file is missing required column(s): {', '.join(missing)}")


def normalize_side(value: object) -> str | None:
    """Map a broker's buy/sell wording onto the trade_type enum."""
    text = str(value).strip().lower()
    if text in ("buy", "bought", "b", "purchase", "buy to open"):
        return "buy"
    if text in ("sell", "sold", "s", "sale", "sell to close"):
        return "sell"
    return None


def parse_date(value: object, formats: Iterable[str] = ("%Y%m%d",)) -> datetime | None:
    """Try the broker's known formats first, then fall back to pandas."""
    text = str(value).strip().split(".")[0]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)  # noqa: DTZ007 - naive, like the column
        except ValueError:
            continue
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(tzinfo=None)


def to_float(value: object, default: float = 0.0) -> float:
    """Broker exports pad numbers with currency symbols, commas and parentheses."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip().replace(",", "").replace("$", "").replace("฿", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    if not text or text in ("-", "--"):
        return default
    try:
        number = float(text)
    except ValueError:
        return default
    return -number if negative else number


def make_source_ref(
    broker: str,
    group_id: int,
    row: TradeRow,
    occurrence: int,
) -> str:
    """Stable id for an imported row.

    Uses the broker's own reference when the export provides one. Otherwise falls back to
    broker + group + symbol + date + side + position among that day's identical fills, which
    stays stable as long as the export lists same-day fills in the same order.

    Quantity and price are deliberately excluded so a corrected export updates the existing
    trade instead of inserting a second one.
    """
    if row.broker_ref:
        raw = f"{broker}|{group_id}|{row.broker_ref}"
    else:
        raw = (
            f"{broker}|{group_id}|{row.symbol.upper()}|"
            f"{row.trade_date:%Y%m%d}|{row.trade_type}|{occurrence}"
        )
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
