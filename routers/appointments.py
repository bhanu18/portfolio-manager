"""
Express Tailoring Appointment Booking API Router.
Paul Bespoke Suits - Bangkok, Thailand

Endpoints:
- POST /api/appointments/book - Create new appointment request
- GET /api/appointments/available-slots - Get available time slots for a date
- GET /api/appointments/{id} - Get appointment details
- PATCH /api/appointments/{id}/confirm - Confirm appointment (admin)
- PATCH /api/appointments/{id}/cancel - Cancel appointment
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, date
from slowapi import Limiter
from slowapi.util import get_remote_address

from db.dependencies import get_db, get_current_active_admin_user
from db import service
from db.orm_models import AppointmentStatus as DBAppointmentStatus
from models import users as user_schema
from models.appointment import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentBookingResponse,
    AvailableSlotsResponse,
    AppointmentStatusUpdate,
    AppointmentListResponse,
    AppointmentStatus,
    ExpressService,
    SERVICE_DISPLAY_NAMES,
    VALID_TIME_SLOTS,
)
from service.appointment import (
    generate_booking_reference,
    validate_appointment_date,
    validate_time_slot,
    calculate_end_time,
    get_service_display_name,
    check_slot_availability,
    get_available_slots_for_date,
    send_customer_confirmation_email,
    send_business_notification_email,
    send_confirmation_status_email,
    get_bangkok_now,
    get_bangkok_date,
    BANGKOK_TZ,
)

router = APIRouter(prefix="/api/appointments", tags=["Appointments"])

# Initialize rate limiter for this router
limiter = Limiter(key_func=get_remote_address)


def convert_to_response(appointment) -> AppointmentResponse:
    """Convert ORM appointment model to response model."""
    return AppointmentResponse(
        id=appointment.id,
        booking_reference=appointment.booking_reference,
        name=appointment.name,
        email=appointment.email,
        phone=appointment.phone,
        date=appointment.date.date() if isinstance(appointment.date, datetime) else appointment.date,
        time_slot=appointment.time_slot,
        express_service=appointment.express_service,
        service_display_name=SERVICE_DISPLAY_NAMES.get(
            ExpressService(appointment.express_service.value),
            appointment.express_service.value
        ),
        garment_details=appointment.garment_details,
        special_requests=appointment.special_requests,
        status=appointment.status,
        estimated_end_time=appointment.estimated_end_time,
        created_at=appointment.created_at,
        updated_at=appointment.updated_at,
    )


@router.post("/book", response_model=AppointmentBookingResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def book_appointment(
    request: Request,
    appointment_data: AppointmentCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new appointment booking request.

    This endpoint allows customers to book an express tailoring appointment.
    The booking is created with 'pending' status and requires admin confirmation.

    **Rate Limiting:** Limited to 10 bookings per hour per IP address to prevent spam.

    **Validation:**
    - Date must be between today and 3 months ahead
    - Time slot must be within business hours (10 AM - 7 PM)
    - Prevents double-booking for the same date/time slot

    Returns the booking details including a unique booking reference number.
    """
    # Validate appointment date
    is_valid_date, date_error = validate_appointment_date(appointment_data.date)
    if not is_valid_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=date_error
        )

    # Validate time slot
    is_valid_slot, slot_error = validate_time_slot(
        appointment_data.time_slot,
        appointment_data.date
    )
    if not is_valid_slot:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=slot_error
        )

    # Check for double-booking
    target_datetime = datetime.combine(appointment_data.date, datetime.min.time())
    existing_appointments = await service.get_appointments_by_date_and_slot(
        db, target_datetime, appointment_data.time_slot
    )

    is_available, availability_error = await check_slot_availability(
        existing_appointments, appointment_data.time_slot
    )
    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=availability_error
        )

    # Generate booking reference and calculate end time
    booking_reference = generate_booking_reference()
    estimated_end = calculate_end_time(
        appointment_data.time_slot,
        appointment_data.express_service
    )

    # Prepare appointment data
    now = get_bangkok_now().replace(tzinfo=None)  # Remove timezone for DB storage
    appointment_dict = {
        "booking_reference": booking_reference,
        "name": appointment_data.name,
        "email": appointment_data.email,
        "phone": appointment_data.phone,
        "date": datetime.combine(appointment_data.date, datetime.min.time()),
        "time_slot": appointment_data.time_slot,
        "express_service": appointment_data.express_service,
        "garment_details": appointment_data.garment_details,
        "special_requests": appointment_data.special_requests,
        "estimated_end_time": estimated_end,
        "status": DBAppointmentStatus.PENDING,
        "created_at": now,
        "updated_at": now,
    }

    # Create appointment in database
    db_appointment = await service.create_appointment(db, appointment_dict)

    # Send emails (non-blocking - don't fail if email fails)
    customer_email_sent = send_customer_confirmation_email(
        customer_name=appointment_data.name,
        customer_email=appointment_data.email,
        booking_reference=booking_reference,
        appointment_date=appointment_data.date,
        time_slot=appointment_data.time_slot,
        service=appointment_data.express_service,
        garment_details=appointment_data.garment_details,
        special_requests=appointment_data.special_requests,
    )

    # Send notification to business (fire and forget)
    send_business_notification_email(
        customer_name=appointment_data.name,
        customer_email=appointment_data.email,
        customer_phone=appointment_data.phone,
        booking_reference=booking_reference,
        appointment_date=appointment_data.date,
        time_slot=appointment_data.time_slot,
        service=appointment_data.express_service,
        garment_details=appointment_data.garment_details,
        special_requests=appointment_data.special_requests,
    )

    return AppointmentBookingResponse(
        success=True,
        message="Appointment booking received successfully. You will receive a confirmation email shortly.",
        appointment=convert_to_response(db_appointment),
        email_sent=customer_email_sent,
    )


@router.get("/available-slots", response_model=AvailableSlotsResponse)
async def get_available_slots(
    request: Request,
    date: date = Query(..., description="Date to check availability (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get available time slots for a specific date.

    Returns all time slots (10 AM - 7 PM) with availability status.
    Slots that are already booked or have passed (for same-day) are marked as unavailable.

    **Validation:**
    - Date must be between today and 3 months ahead
    """
    # Validate date
    is_valid_date, date_error = validate_appointment_date(date)
    if not is_valid_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=date_error
        )

    # Get existing appointments for this date
    target_datetime = datetime.combine(date, datetime.min.time())
    existing_appointments = await service.get_appointments_by_date(db, target_datetime)

    # Get availability for all slots
    slots = get_available_slots_for_date(date, existing_appointments)

    return AvailableSlotsResponse(
        date=date,
        slots=slots,
        business_hours="10:00 AM - 7:00 PM"
    )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get appointment details by ID.

    This endpoint can be used by customers to check their appointment status
    or by admins to review appointment details.
    """
    appointment = await service.get_appointment_by_id(db, appointment_id)

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with ID {appointment_id} not found"
        )

    return convert_to_response(appointment)


@router.get("/reference/{booking_reference}", response_model=AppointmentResponse)
async def get_appointment_by_reference(
    booking_reference: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get appointment details by booking reference number.

    Customers can use their booking reference (e.g., PBS-20250125-ABC123)
    to look up their appointment status.
    """
    appointment = await service.get_appointment_by_reference(db, booking_reference)

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with reference '{booking_reference}' not found"
        )

    return convert_to_response(appointment)


@router.patch("/{appointment_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment(
    appointment_id: int,
    status_update: AppointmentStatusUpdate = None,
    db: AsyncSession = Depends(get_db),
    current_admin: user_schema.User = Depends(get_current_active_admin_user)
):
    """
    Confirm a pending appointment (Admin only).

    Changes the appointment status from 'pending' to 'confirmed'.
    Sends a confirmation email to the customer.

    **Authorization:** Requires admin privileges.
    """
    appointment = await service.get_appointment_by_id(db, appointment_id)

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with ID {appointment_id} not found"
        )

    if appointment.status == DBAppointmentStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Appointment is already confirmed"
        )

    if appointment.status == DBAppointmentStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot confirm a cancelled appointment"
        )

    if appointment.status == DBAppointmentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot confirm a completed appointment"
        )

    # Update status
    admin_notes = status_update.notes if status_update else None
    updated_appointment = await service.update_appointment_status(
        db, appointment, DBAppointmentStatus.CONFIRMED, admin_notes
    )

    # Send confirmation email to customer
    appointment_date = appointment.date.date() if isinstance(appointment.date, datetime) else appointment.date
    send_confirmation_status_email(
        customer_name=appointment.name,
        customer_email=appointment.email,
        booking_reference=appointment.booking_reference,
        appointment_date=appointment_date,
        time_slot=appointment.time_slot,
        service=ExpressService(appointment.express_service.value),
        status=AppointmentStatus.CONFIRMED.value,
        admin_notes=admin_notes,
    )

    return convert_to_response(updated_appointment)


@router.patch("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: int,
    status_update: AppointmentStatusUpdate = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel an appointment.

    Changes the appointment status to 'cancelled'.
    Sends a cancellation notification email to the customer.

    This endpoint can be used by customers to cancel their own appointments
    or by admins to cancel bookings.

    Note: For a production system, you would want to add authentication
    to verify the customer owns this appointment or is an admin.
    """
    appointment = await service.get_appointment_by_id(db, appointment_id)

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with ID {appointment_id} not found"
        )

    if appointment.status == DBAppointmentStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Appointment is already cancelled"
        )

    if appointment.status == DBAppointmentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a completed appointment"
        )

    # Update status
    admin_notes = status_update.notes if status_update else None
    updated_appointment = await service.update_appointment_status(
        db, appointment, DBAppointmentStatus.CANCELLED, admin_notes
    )

    # Send cancellation email to customer
    appointment_date = appointment.date.date() if isinstance(appointment.date, datetime) else appointment.date
    send_confirmation_status_email(
        customer_name=appointment.name,
        customer_email=appointment.email,
        booking_reference=appointment.booking_reference,
        appointment_date=appointment_date,
        time_slot=appointment.time_slot,
        service=ExpressService(appointment.express_service.value),
        status=AppointmentStatus.CANCELLED.value,
        admin_notes=admin_notes,
    )

    return convert_to_response(updated_appointment)


@router.patch("/{appointment_id}/complete", response_model=AppointmentResponse)
async def complete_appointment(
    appointment_id: int,
    status_update: AppointmentStatusUpdate = None,
    db: AsyncSession = Depends(get_db),
    current_admin: user_schema.User = Depends(get_current_active_admin_user)
):
    """
    Mark an appointment as completed (Admin only).

    Changes the appointment status from 'confirmed' to 'completed'.

    **Authorization:** Requires admin privileges.
    """
    appointment = await service.get_appointment_by_id(db, appointment_id)

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with ID {appointment_id} not found"
        )

    if appointment.status == DBAppointmentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Appointment is already completed"
        )

    if appointment.status == DBAppointmentStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete a cancelled appointment"
        )

    if appointment.status == DBAppointmentStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete a pending appointment. Please confirm it first."
        )

    # Update status
    admin_notes = status_update.notes if status_update else None
    updated_appointment = await service.update_appointment_status(
        db, appointment, DBAppointmentStatus.COMPLETED, admin_notes
    )

    return convert_to_response(updated_appointment)


# Admin endpoints for listing and managing appointments

@router.get("/", response_model=AppointmentListResponse)
async def list_appointments(
    request: Request,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of records to return"),
    status: Optional[str] = Query(None, description="Filter by status (pending, confirmed, cancelled, completed)"),
    from_date: Optional[date] = Query(None, description="Filter appointments from this date"),
    to_date: Optional[date] = Query(None, description="Filter appointments up to this date"),
    db: AsyncSession = Depends(get_db),
    current_admin: user_schema.User = Depends(get_current_active_admin_user)
):
    """
    List all appointments with optional filtering (Admin only).

    **Filters:**
    - status: Filter by appointment status
    - from_date: Filter appointments from this date onwards
    - to_date: Filter appointments up to this date

    **Pagination:**
    - skip: Number of records to skip (default: 0)
    - limit: Maximum records to return (default: 100, max: 500)

    **Authorization:** Requires admin privileges.
    """
    # Convert dates to datetime if provided
    from_datetime = datetime.combine(from_date, datetime.min.time()) if from_date else None
    to_datetime = datetime.combine(to_date, datetime.max.time()) if to_date else None

    # Get appointments
    appointments = await service.get_all_appointments(
        db,
        skip=skip,
        limit=limit,
        status=status,
        from_date=from_datetime,
        to_date=to_datetime
    )

    # Get total count
    total = await service.count_appointments(
        db,
        status=status,
        from_date=from_datetime,
        to_date=to_datetime
    )

    return AppointmentListResponse(
        total=total,
        appointments=[convert_to_response(appt) for appt in appointments]
    )


@router.get("/services", response_model=dict)
async def get_available_services():
    """
    Get list of available express tailoring services with their estimated times.

    Returns all service types with display names for frontend dropdowns.
    """
    return {
        "services": [
            {
                "value": service.value,
                "label": SERVICE_DISPLAY_NAMES[service],
            }
            for service in ExpressService
        ],
        "time_slots": VALID_TIME_SLOTS,
        "business_hours": {
            "open": "10:00 AM",
            "close": "7:00 PM",
            "timezone": "Asia/Bangkok"
        }
    }
