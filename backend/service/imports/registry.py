"""Broker parser registry and file sniffing."""

from __future__ import annotations

import pandas as pd

from service.imports.base import BrokerParser, ParseError, TradeRow
from service.imports.yahoo import YahooParser

PARSERS: dict[str, BrokerParser] = {
    parser.code: parser
    for parser in (
        YahooParser(),
        # DimeParser(),       # pending a sample export
        # WebullThParser(),   # pending a sample export
    )
}


def read_table(path: str) -> pd.DataFrame:
    """Read a broker export. Handles CSV and Excel, which brokers use interchangeably."""
    if path.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path)


def sniff_broker(df: pd.DataFrame) -> BrokerParser:
    """Pick the parser whose signature matches the file's columns."""
    candidates = [p for p in PARSERS.values() if p.matches(df.columns)]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ParseError(
            "could not tell which broker this file is from; pass --broker "
            f"({', '.join(sorted(PARSERS))})"
        )
    names = ", ".join(p.code for p in candidates)
    raise ParseError(f"file matches more than one broker ({names}); pass --broker")


def get_parser(code: str) -> BrokerParser:
    try:
        return PARSERS[code]
    except KeyError:
        raise ParseError(
            f"unknown broker {code!r}; available: {', '.join(sorted(PARSERS))}"
        ) from None


def parse_file(path: str, broker: str | None = None) -> tuple[BrokerParser, list[TradeRow]]:
    """Read and parse a broker export, auto-detecting the broker when not given."""
    df = read_table(path)
    parser = get_parser(broker) if broker else sniff_broker(df)
    return parser, parser.parse(df)
