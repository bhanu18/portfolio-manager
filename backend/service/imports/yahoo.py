"""Parser for Yahoo Finance portfolio exports."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from service.imports.base import (
    ParseError,
    TradeRow,
    normalize_side,
    parse_date,
    require_columns,
    to_float,
)

REQUIRED = ("Symbol", "Trade Date", "Purchase Price", "Quantity", "Transaction Type")


class YahooParser:
    code = "yahoo"
    label = "Yahoo Finance"
    # The original CSV importer wrote refs under "csv"; keep that so trades imported
    # before the multi-broker refactor are updated rather than duplicated.
    ref_prefix = "csv"

    def matches(self, columns: Iterable[str]) -> bool:
        present = set(columns)
        # "Current Price" and "High Limit" together are distinctive to Yahoo's export.
        return {"Symbol", "Trade Date", "Purchase Price"} <= present and (
            "High Limit" in present or "Current Price" in present
        )

    def parse(self, df: pd.DataFrame) -> list[TradeRow]:
        require_columns(df.columns, REQUIRED)

        rows: list[TradeRow] = []
        for position, (_, raw) in enumerate(df.iterrows(), start=2):  # line 1 is the header
            side = normalize_side(raw.get("Transaction Type", "buy"))
            if side is None:
                rows.append(
                    _skipped(position, f"unknown Transaction Type {raw.get('Transaction Type')!r}")
                )
                continue

            trade_date = parse_date(raw["Trade Date"], formats=("%Y%m%d", "%Y/%m/%d", "%m/%d/%Y"))
            if trade_date is None:
                rows.append(_skipped(position, f"unparseable Trade Date {raw['Trade Date']!r}"))
                continue

            quantity = to_float(raw["Quantity"])
            price = to_float(raw["Purchase Price"])
            symbol = str(raw["Symbol"]).strip().upper()
            if not symbol or quantity <= 0 or price <= 0:
                rows.append(_skipped(position, "missing symbol, quantity or price"))
                continue

            rows.append(
                TradeRow(
                    symbol=symbol,
                    trade_type=side,
                    trade_date=trade_date,
                    quantity=quantity,
                    price_per_unit=price,
                    currency="USD",  # Yahoo's export carries no currency column
                    fee=to_float(raw.get("Commission")),
                )
            )

        valid = [r for r in rows if r.quantity > 0]
        if not valid and rows:
            raise ParseError("no usable trades found in the Yahoo export")
        return rows


def _skipped(line: int, reason: str) -> TradeRow:
    """A placeholder row the pipeline drops, carrying the reason for the operator."""
    from datetime import datetime

    return TradeRow(
        symbol="",
        trade_type="buy",
        trade_date=datetime(1970, 1, 1),  # noqa: DTZ001 - sentinel, never stored
        quantity=0.0,
        price_per_unit=0.0,
        warnings=[f"line {line}: {reason}"],
    )
