from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime

class Asset(BaseModel):
    """
    Represents a single asset in the portfolio, like a stock or cryptocurrency.
    """
    id: int
    symbol: str
    name: str
    market: str
    
    type: Literal['stock', 'crypto', 'cash']
    
    # We'll make current_price optional as it will be populated by our API
    current_price: Optional[float] = None
    
    price_last_updated: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

# Let's also create a Pydantic model for the request body
# This defines what the user needs to send when creating an asset.
# Notice 'current_price' is not here because the user won't provide it.
class AssetCreate(BaseModel):
    symbol: str
    name: str
    market: str
    type: Literal['stock', 'crypto', 'cash']