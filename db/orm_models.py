from sqlalchemy import Column, String, Float, DateTime, Enum, Integer, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), index=True)
    trade_type = Column(Enum('buy', 'sell', name='trade_type_enum'), nullable=False)
    trade_date = Column(DateTime, nullable=False)
    quantity = Column(Float, nullable=False)
    price_per_unit = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, server_default='USD')  # Default currency for the trade
    
class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    symbol = Column(String(10), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    market = Column(String(50), nullable=False)
    current_price = Column(Float, nullable=True)  # Optional, will be populated by the API
    type = Column(String(10), nullable=False)  # e.g., stock, crypto, cash
    price_last_updated = Column(DateTime, nullable=True)  # Optional, will be populated by the API
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

# class User(Base):
#     __tablename__ = "users"

#     id = Column(Integer, primary_key=True, index=True)
#     name = Column(String, unique=True, index=True, nullable=False)
#     email = Column(String, unique=True, index=True, nullable=False)
#     hashed_password = Column(String, nullable=False)
#     created_at = Column(DateTime, nullable=False)
#     updated_at = Column(DateTime, nullable=False)