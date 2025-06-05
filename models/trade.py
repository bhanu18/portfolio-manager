from pydantic import BaseModel
from datetime import datetime
from typing import Literal

class Trade(BaseModel):
    """
    Represents a single transaction (a buy or a sell) for an asset.
    This is the foundation for calculating portfolio performance.
    """
    id: int  # A unique ID for the trade itself
    asset_id: int  # The ID of the asset being traded
    
    # The type of trade
    trade_type: Literal['buy', 'sell']
    
    # The exact date and time of the trade
    trade_date: datetime
    
    # The number of units (e.g., shares, coins) traded
    quantity: float
    
    # The price of a single unit at the time of the trade
    price_per_unit: float
    currency: str  # Default currency for the trade, can be overridden
    
class TradeCreate(BaseModel):
    trade_type: Literal['buy', 'sell']
    trade_date: datetime
    quantity: float
    price_per_unit: float
    currency: str