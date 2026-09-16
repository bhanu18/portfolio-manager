from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# This model defines the structure of the data we will SEND to the user.
class TradeResponse(BaseModel):
    """
    A response model for a trade that includes the asset's symbol
    instead of its ID.
    """

    id: str
    symbol: str  # <-- The key difference: we show symbol
    trade_type: Literal["buy", "sell"]
    trade_date: datetime
    quantity: float
    price_per_unit: float
