"""Shared import pipeline: resolve assets, then upsert trades idempotently.

Used by both the CLI (scripts/import_trades.py) and the API endpoint, so a file
imported either way produces exactly the same rows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.orm_models import Asset, Group, Trade
from service.imports.base import TradeRow, make_source_ref

TRADE_FIELDS = (
    "asset_id",
    "trade_type",
    "trade_date",
    "quantity",
    "price_per_unit",
    "currency",
    "group_id",
)


@dataclass
class ImportResult:
    """What an import did, for the CLI to print and the API to return."""

    broker: str
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    assets_created: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


class ImportError_(Exception):
    """Import cannot proceed (bad group, unresolvable assets, ...)."""


# quantity and price_per_unit are FLOAT columns, and MySQL hands them back at roughly
# six significant digits, so an exact == would report a change on every re-import.
# Anything closer than this is treated as the same value; real broker corrections are
# orders of magnitude larger. (Moving those columns to DECIMAL would remove the need.)
FLOAT_REL_TOL = 1e-5
FLOAT_ABS_TOL = 1e-6


def _same(stored: object, incoming: object) -> bool:
    """Compare a stored value with an incoming one, tolerating FLOAT precision loss."""
    if isinstance(stored, float) and isinstance(incoming, int | float):
        return math.isclose(stored, float(incoming), rel_tol=FLOAT_REL_TOL, abs_tol=FLOAT_ABS_TOL)
    return bool(stored == incoming)


async def ensure_group_exists(db: AsyncSession, group_id: int) -> None:
    result = await db.execute(select(Group.id).where(Group.id == group_id))
    if result.scalar_one_or_none() is None:
        raise ImportError_(f"Group id {group_id} does not exist")


async def fetch_asset_ids(db: AsyncSession, symbols: list[str]) -> dict[str, int]:
    result = await db.execute(select(Asset.symbol, Asset.id).where(Asset.symbol.in_(symbols)))
    return {row.symbol: row.id for row in result.all()}


def lookup_asset_details(symbols: list[str]) -> dict[str, dict]:
    """Name/market/type for new symbols, with safe defaults when the lookup fails."""
    if not symbols:
        return {}

    tickers = yf.Tickers(" ".join(symbols))
    details: dict[str, dict] = {}
    for symbol in symbols:
        try:
            info = tickers.tickers[symbol].info
            details[symbol] = {
                "name": info.get("longName") or symbol,
                "market": info.get("exchange") or "Unknown",
                "type": (info.get("quoteType") or "EQUITY").lower(),
            }
        except Exception:
            details[symbol] = {"name": symbol, "market": "Unknown", "type": "stock"}
    return details


async def resolve_assets(
    db: AsyncSession, symbols: list[str], result: ImportResult, dry_run: bool
) -> dict[str, int]:
    """Map symbols to asset ids, creating the ones that don't exist yet."""
    asset_ids = await fetch_asset_ids(db, symbols)
    missing = [s for s in symbols if s not in asset_ids]
    if not missing:
        return asset_ids

    if dry_run:
        result.assets_created = missing
        return {**asset_ids, **{symbol: -1 for symbol in missing}}

    details = lookup_asset_details(missing)
    now = datetime.now()  # noqa: DTZ005 - created_at/updated_at are naive columns
    db.add_all(
        [
            Asset(
                symbol=symbol,
                name=details[symbol]["name"],
                market=details[symbol]["market"],
                type=details[symbol]["type"],
                current_price=None,
                created_at=now,
                updated_at=now,
            )
            for symbol in missing
        ]
    )
    await db.commit()
    result.assets_created = missing
    for symbol in missing:
        if details[symbol]["market"] == "Unknown":
            result.warnings.append(f"{symbol}: could not fetch asset details; using defaults")
    return await fetch_asset_ids(db, symbols)


def to_payloads(rows: list[TradeRow], broker: str, group_id: int) -> list[dict]:
    """Normalized rows -> trade payloads with fee folded in and a source_ref attached."""
    occurrences: dict[tuple[str, str, str], int] = {}
    payloads: list[dict] = []
    for row in rows:
        key = (row.symbol, f"{row.trade_date:%Y%m%d}", row.trade_type)
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        payloads.append(
            {
                "symbol": row.symbol,
                "trade_type": row.trade_type,
                "trade_date": row.trade_date,
                "quantity": row.quantity,
                "price_per_unit": round(row.effective_price(), 4),
                "currency": row.currency,
                "group_id": group_id,
                "source_ref": make_source_ref(broker, group_id, row, occurrence),
            }
        )
    return payloads


async def upsert_trades(
    db: AsyncSession, payloads: list[dict], result: ImportResult, dry_run: bool
) -> None:
    """Insert new trades, update changed ones, leave identical ones untouched."""
    refs = [p["source_ref"] for p in payloads]
    existing_rows = await db.execute(select(Trade).where(Trade.source_ref.in_(refs)))
    existing = {t.source_ref: t for t in existing_rows.scalars().all()}

    to_insert = []
    for payload in payloads:
        current = existing.get(payload["source_ref"])
        if current is None:
            to_insert.append(
                Trade(
                    **{f: payload[f] for f in TRADE_FIELDS},
                    source_ref=payload["source_ref"],
                )
            )
            result.inserted += 1
            continue

        changes = {
            field_name: payload[field_name]
            for field_name in TRADE_FIELDS
            if not _same(getattr(current, field_name), payload[field_name])
        }
        if not changes:
            result.unchanged += 1
            continue

        result.updated += 1
        result.changes.append(
            f"{payload['symbol']} {payload['trade_type']} {payload['trade_date']:%Y-%m-%d}: "
            + ", ".join(f"{k} {getattr(current, k)} -> {v}" for k, v in changes.items())
        )
        if not dry_run:
            for field_name, value in changes.items():
                setattr(current, field_name, value)

    if not dry_run:
        db.add_all(to_insert)
        await db.commit()


async def import_trades(
    db: AsyncSession,
    rows: list[TradeRow],
    broker: str,
    group_id: int,
    dry_run: bool = False,
    ref_prefix: str | None = None,
) -> ImportResult:
    """Run a parsed broker export through asset resolution and the upsert."""
    result = ImportResult(broker=broker, dry_run=dry_run)
    ref_prefix = ref_prefix or broker

    usable = []
    for row in rows:
        result.warnings.extend(row.warnings)
        if row.quantity <= 0 or not row.symbol:
            result.skipped += 1
            continue
        usable.append(row)

    if not usable:
        return result

    await ensure_group_exists(db, group_id)

    symbols = sorted({row.symbol for row in usable})
    asset_ids = await resolve_assets(db, symbols, result, dry_run)

    payloads = []
    for payload in to_payloads(usable, ref_prefix, group_id):
        asset_id = asset_ids.get(payload["symbol"])
        if asset_id is None:
            result.warnings.append(f"{payload['symbol']}: no asset id; skipped")
            result.skipped += 1
            continue
        payloads.append({**payload, "asset_id": asset_id})

    if payloads:
        await upsert_trades(db, payloads, result, dry_run)
    return result
