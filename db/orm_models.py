from sqlalchemy import Column, String, Float, DateTime, Integer, ForeignKey, Boolean
from sqlalchemy import Enum as SQLAlchemyEnum, Table
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.hybrid import hybrid_property
import enum

Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), index=True, nullable=False)
    trade_type = Column(SQLAlchemyEnum('buy', 'sell', name='trade_type_enum'), nullable=False)
    trade_date = Column(DateTime, nullable=False)
    quantity = Column(Float, nullable=False)
    price_per_unit = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, server_default='USD')  # Default currency for the trade
    
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    group = relationship("Group", back_populates="trades")
    
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

class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    
class GroupMemberRole(str, enum.Enum):
    MEMBER = "member"
    ADMIN = "group_admin" # This is our "Group Admin"

class UserGroupAssociation(Base):
    __tablename__ = "user_group_association"
    user_id = Column(ForeignKey("users.id"), primary_key=True)
    group_id = Column(ForeignKey("groups.id"), primary_key=True)
    role = Column(SQLAlchemyEnum(GroupMemberRole), nullable=False, default=GroupMemberRole.MEMBER)
    
    # Relationships back to User and Group
    user = relationship("User", back_populates="group_associations")
    group = relationship("Group", back_populates="member_associations")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)
    role = Column(SQLAlchemyEnum(UserRole), nullable=False, default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    group_associations = relationship("UserGroupAssociation", back_populates="user")
    
    @hybrid_property
    def groups(self):
        """
        A "computed" property that provides a direct list of Group objects.
        Pydantic's `from_attributes=True` will see and use this automatically.
        """
        return [association.group for association in self.group_associations]
    
class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    trades = relationship("Trade", back_populates="group")    
    member_associations = relationship("UserGroupAssociation", back_populates="group")
    
    @hybrid_property
    def members(self):
        """
        A 'computed' property that provides a direct list of User objects
        from the association objects. Pydantic will use this automatically.
        """
        return [association.user for association in self.member_associations]


class AppointmentStatus(str, enum.Enum):
    """Status values for appointments."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ExpressServiceType(str, enum.Enum):
    """Available express tailoring services."""
    HEM_PANTS = "hem_pants"
    SHORTEN_SLEEVES = "shorten_sleeves"
    TAKE_IN_WAIST = "take_in_waist"
    TAKE_IN_SIDES = "take_in_sides"
    BUTTON_REPLACEMENT = "button_replacement"
    ZIPPER_REPAIR = "zipper_repair"
    EMERGENCY_REPAIR = "emergency_repair"
    EXPRESS_CUSTOM_SHIRT = "express_custom_shirt"
    OTHER = "other"


class Appointment(Base):
    """
    Express Tailoring Appointment model for Paul Bespoke Suits.
    Stores customer booking information and appointment status.
    """
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Booking reference (unique identifier for customers)
    booking_reference = Column(String(50), unique=True, nullable=False, index=True)

    # Customer information
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(20), nullable=False)

    # Appointment scheduling
    date = Column(DateTime, nullable=False, index=True)  # Stores date portion
    time_slot = Column(String(20), nullable=False)  # e.g., "2:00 PM"
    estimated_end_time = Column(String(20), nullable=True)  # Calculated end time

    # Service details
    express_service = Column(
        SQLAlchemyEnum(ExpressServiceType, name='express_service_enum'),
        nullable=False
    )
    garment_details = Column(String(500), nullable=True)
    special_requests = Column(String(500), nullable=True)

    # Status tracking
    status = Column(
        SQLAlchemyEnum(AppointmentStatus, name='appointment_status_enum'),
        nullable=False,
        default=AppointmentStatus.PENDING
    )
    admin_notes = Column(String(500), nullable=True)  # Notes from admin on confirm/cancel

    # Timestamps
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)