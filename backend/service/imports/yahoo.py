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
    skipped_row,
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
                    skipped_row(
                        position, f"unknown Transaction Type {raw.get('Transaction Type')!r}"
                    )
                )
                continue

            trade_date = parse_date(raw["Trade Date"], formats=("%Y%m%d", "%Y/%m/%d", "%m/%d/%Y"))
            if trade_date is None:
                rows.append(skipped_row(position, f"unparseable Trade Date {raw['Trade Date']!r}"))
                continue

            quantity = to_float(raw["Quantity"])
            price = to_float(raw["Purchase Price"])
            symbol = str(raw["Symbol"]).strip().upper()
            if not symbol or quantity <= 0 or price <= 0:
                rows.append(skipped_row(position, "missing symbol, quantity or price"))
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
