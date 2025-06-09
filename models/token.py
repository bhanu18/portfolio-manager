from pydantic import BaseModel
from typing import Optional

class TokenData(BaseModel):
    email: Optional[str] = None