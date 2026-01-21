"""
Pydantic models for Express Tailoring appointment booking system.
Paul Bespoke Suits - Bangkok, Thailand
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime, date as date_type, time
from typing import Optional, List
from enum import Enum


class ExpressService(str, Enum):
    """Available express tailoring services with estimated completion times."""
    HEM_PANTS = "hem_pants"  # 1-2 hours
    SHORTEN_SLEEVES = "shorten_sleeves"  # 2-3 hours
    TAKE_IN_WAIST = "take_in_waist"  # 2-3 hours
    TAKE_IN_SIDES = "take_in_sides"  # 3-4 hours
    BUTTON_REPLACEMENT = "button_replacement"  # 30 mins
    ZIPPER_REPAIR = "zipper_repair"  # 1-2 hours
    EMERGENCY_REPAIR = "emergency_repair"  # Same day
    EXPRESS_CUSTOM_SHIRT = "express_custom_shirt"  # 24-48 hours
    OTHER = "other"  # TBD


class AppointmentStatus(str, Enum):
    """Appointment status values."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


# Service duration mapping in minutes (using maximum estimated time)
SERVICE_DURATIONS = {
    ExpressService.HEM_PANTS: 120,  # 2 hours
    ExpressService.SHORTEN_SLEEVES: 180,  # 3 hours
    ExpressService.TAKE_IN_WAIST: 180,  # 3 hours
    ExpressService.TAKE_IN_SIDES: 240,  # 4 hours
    ExpressService.BUTTON_REPLACEMENT: 30,  # 30 mins
    ExpressService.ZIPPER_REPAIR: 120,  # 2 hours
    ExpressService.EMERGENCY_REPAIR: 480,  # Full day (8 hours)
    ExpressService.EXPRESS_CUSTOM_SHIRT: 480,  # Full day slot
    ExpressService.OTHER: 60,  # Default 1 hour
}

# Service display names for emails and responses
SERVICE_DISPLAY_NAMES = {
    ExpressService.HEM_PANTS: "Hem Pants/Trousers (1-2 hours)",
    ExpressService.SHORTEN_SLEEVES: "Shorten Jacket Sleeves (2-3 hours)",
    ExpressService.TAKE_IN_WAIST: "Take In Waist (2-3 hours)",
    ExpressService.TAKE_IN_SIDES: "Take In Sides (3-4 hours)",
    ExpressService.BUTTON_REPLACEMENT: "Button Replacement (30 mins)",
    ExpressService.ZIPPER_REPAIR: "Zipper Repair (1-2 hours)",
    ExpressService.EMERGENCY_REPAIR: "Emergency Repair (Same day)",
    ExpressService.EXPRESS_CUSTOM_SHIRT: "Express Custom Shirt (24-48 hours)",
    ExpressService.OTHER: "Other Service (TBD)",
}

# Valid time slots (10 AM - 7 PM Bangkok time)
VALID_TIME_SLOTS = [
    "10:00 AM", "11:00 AM", "12:00 PM", "1:00 PM",
    "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM",
    "6:00 PM", "7:00 PM"
]


class AppointmentCreate(BaseModel):
    """Request model for creating a new appointment booking."""
    name: str = Field(..., min_length=2, max_length=100, description="Customer name")
    email: EmailStr = Field(..., description="Customer email address")
    phone: str = Field(..., min_length=8, max_length=20, description="Customer phone number")
    appointment_date: date_type = Field(..., alias="date", description="Appointment date (YYYY-MM-DD)")
    time_slot: str = Field(..., alias="timeSlot", description="Appointment time slot (e.g., '2:00 PM')")
    express_service: ExpressService = Field(..., alias="expressService", description="Type of express service")
    garment_details: Optional[str] = Field(None, alias="garmentDetails", max_length=500, description="Garment details")
    special_requests: Optional[str] = Field(None, alias="specialRequests", max_length=500, description="Special requests")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+66812345678",
                "date": "2025-01-25",
                "timeSlot": "2:00 PM",
                "expressService": "hem_pants",
                "garmentDetails": "Blue jeans, need 2 inches off",
                "specialRequests": "Rush if possible"
            }
        }
    }

    @field_validator("time_slot")
    @classmethod
    def validate_time_slot(cls, v: str) -> str:
        """Validate that time slot is within business hours."""
        if v not in VALID_TIME_SLOTS:
            raise ValueError(f"Invalid time slot. Must be one of: {', '.join(VALID_TIME_SLOTS)}")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Basic phone number validation."""
        # Remove common formatting characters for validation
        cleaned = v.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not cleaned.replace("+", "").isdigit():
            raise ValueError("Phone number must contain only digits, spaces, dashes, parentheses, and optional + prefix")
        return v


class AppointmentResponse(BaseModel):
    """Response model for appointment data."""
    id: int
    booking_reference: str
    name: str
    email: str
    phone: str
    appointment_date: date_type = Field(..., alias="date")
    time_slot: str
    express_service: ExpressService
    service_display_name: str
    garment_details: Optional[str] = None
    special_requests: Optional[str] = None
    status: AppointmentStatus
    estimated_end_time: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "id": 1,
                "booking_reference": "PBS-20250125-ABC123",
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+66812345678",
                "date": "2025-01-25",
                "time_slot": "2:00 PM",
                "express_service": "hem_pants",
                "service_display_name": "Hem Pants/Trousers (1-2 hours)",
                "garment_details": "Blue jeans, need 2 inches off",
                "special_requests": "Rush if possible",
                "status": "pending",
                "estimated_end_time": "4:00 PM",
                "created_at": "2025-01-20T10:30:00",
                "updated_at": "2025-01-20T10:30:00"
            }
        }
    }


class AppointmentBookingResponse(BaseModel):
    """Response model for successful appointment booking."""
    success: bool
    message: str
    appointment: AppointmentResponse
    email_sent: bool = False


class AvailableSlot(BaseModel):
    """Model for available time slot."""
    time_slot: str
    available: bool
    reason: Optional[str] = None


class AvailableSlotsResponse(BaseModel):
    """Response model for available slots query."""
    query_date: date_type = Field(..., alias="date")
    slots: List[AvailableSlot]
    business_hours: str = "10:00 AM - 7:00 PM"

    model_config = {
        "populate_by_name": True,
    }


class AppointmentStatusUpdate(BaseModel):
    """Model for appointment status updates (confirm/cancel)."""
    notes: Optional[str] = Field(None, max_length=500, description="Optional notes for status update")


class AppointmentListResponse(BaseModel):
    """Response model for listing appointments (admin)."""
    total: int
    appointments: List[AppointmentResponse]


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
    error_code: Optional[str] = None
