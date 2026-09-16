from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Trade(BaseModel):
    """
    Represents a single transaction (a buy or a sell) for an asset.
    This is the foundation for calculating portfolio performance.
    """

    id: int  # A unique ID for the trade itself
    asset_id: int  # The ID of the asset being traded

    # The type of trade
    trade_type: Literal["buy", "sell"]

    # The exact date and time of the trade
    trade_date: datetime

    # The number of units (e.g., shares, coins) traded
    quantity: float

    # The price of a single unit at the time of the trade
    price_per_unit: float
    currency: str  # Default currency for the trade, can be overridden
    group_id: int  # The group ID to which this trade belongs


class TradeCreate(BaseModel):
    trade_type: Literal["buy", "sell"]
    trade_date: datetime
    quantity: float
    price_per_unit: float
    currency: str
    group_id: int  # The group ID to which this trade belongs


class TradeBase(BaseModel):
    asset_id: int
    trade_type: Literal["buy", "sell"]
    trade_date: datetime
    quantity: float
    price_per_unit: float
    currency: str


class TradeUpdate(BaseModel):
    """Properties to receive on trade update."""

    asset_id: int | None = None
    trade_type: Literal["buy", "sell"] | None = None
    trade_date: datetime | None = None
    quantity: float | None = None
    price_per_unit: float | None = None
    currency: str | None = None
