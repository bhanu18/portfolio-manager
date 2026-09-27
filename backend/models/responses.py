from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# This model defines the structure of the data we will SEND to the user.
class TradeResponse(BaseModel):
    """
    A response model for a trade that includes the asset's symbol
    instead of its ID.
    """

    # The trades table's integer PK. This was `str`, which pydantic v2 refuses to
    # coerce from an int, so every request to GET /trades/symbol/{symbol} failed
    # validation with a 500.
    id: int
    symbol: str  # <-- The key difference: we show symbol
    trade_type: Literal["buy", "sell"]
    trade_date: datetime
    quantity: float
    price_per_unit: float
    currency: str  # The trade's own currency, which need not be the asset's.

    # Row bookkeeping — see models.trade.Trade.
    created_at: datetime
    updated_at: datetime
