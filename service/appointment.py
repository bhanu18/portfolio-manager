"""
Appointment business logic service for Express Tailoring.
Paul Bespoke Suits - Bangkok, Thailand

Handles:
- Booking reference generation
- Date/time validation (Bangkok timezone)
- Availability checking and double-booking prevention
- Service duration calculation
- Email notifications
"""
import secrets
import string
from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple
from zoneinfo import ZoneInfo

from models.appointment import (
    ExpressService,
    AppointmentStatus,
    SERVICE_DURATIONS,
    SERVICE_DISPLAY_NAMES,
    VALID_TIME_SLOTS,
    AppointmentCreate,
    AvailableSlot,
)
from service.email import email_service
from core.config import settings


# Bangkok timezone
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

# Business configuration
BUSINESS_NAME = "Paul Bespoke Suits"
BUSINESS_ADDRESS = "Bangkok, Thailand"
BUSINESS_PHONE = "+66 2 XXX XXXX"  # Replace with actual phone
BUSINESS_EMAIL = settings.EMAIL_FROM or settings.SMTP_USER

# Booking window: today to 3 months ahead
MAX_ADVANCE_BOOKING_DAYS = 90


def get_bangkok_now() -> datetime:
    """Returns current datetime in Bangkok timezone."""
    return datetime.now(BANGKOK_TZ)


def get_bangkok_date() -> date:
    """Returns current date in Bangkok timezone."""
    return get_bangkok_now().date()


def generate_booking_reference() -> str:
    """
    Generates a unique booking reference number.
    Format: PBS-YYYYMMDD-XXXXXX (e.g., PBS-20250125-A3B7K9)
    """
    today = get_bangkok_date()
    date_part = today.strftime("%Y%m%d")
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"PBS-{date_part}-{random_part}"


def validate_appointment_date(appointment_date: date) -> Tuple[bool, Optional[str]]:
    """
    Validates that the appointment date is within allowed range.

    Rules:
    - Cannot book in the past
    - Cannot book more than 3 months (90 days) in advance

    Returns:
        Tuple of (is_valid, error_message)
    """
    today = get_bangkok_date()
    max_date = today + timedelta(days=MAX_ADVANCE_BOOKING_DAYS)

    if appointment_date < today:
        return False, "Cannot book appointments in the past"

    if appointment_date > max_date:
        return False, f"Cannot book more than {MAX_ADVANCE_BOOKING_DAYS} days in advance. Maximum date: {max_date.isoformat()}"

    return True, None


def validate_time_slot(time_slot: str, appointment_date: date) -> Tuple[bool, Optional[str]]:
    """
    Validates the time slot against business hours.

    For same-day bookings, ensures the time hasn't passed.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if time_slot not in VALID_TIME_SLOTS:
        return False, f"Invalid time slot. Available slots: {', '.join(VALID_TIME_SLOTS)}"

    # For same-day bookings, check if the time has passed
    today = get_bangkok_date()
    if appointment_date == today:
        now = get_bangkok_now()
        slot_time = parse_time_slot(time_slot)
        slot_datetime = datetime.combine(today, slot_time, tzinfo=BANGKOK_TZ)

        if slot_datetime <= now:
            return False, f"This time slot ({time_slot}) has already passed today. Please select a later time."

    return True, None


def parse_time_slot(time_slot: str) -> datetime.time:
    """
    Parses time slot string to time object.
    Handles formats like "2:00 PM", "10:00 AM"
    """
    from datetime import time as dt_time

    # Parse the time string
    time_str = time_slot.upper().strip()

    # Handle 12-hour format
    if "PM" in time_str:
        time_str = time_str.replace("PM", "").strip()
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if hour != 12:
            hour += 12
    else:  # AM
        time_str = time_str.replace("AM", "").strip()
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if hour == 12:
            hour = 0

    return dt_time(hour=hour, minute=minute)


def calculate_end_time(time_slot: str, service: ExpressService) -> str:
    """
    Calculates estimated end time based on service duration.

    Returns:
        Formatted end time string (e.g., "4:00 PM")
    """
    start_time = parse_time_slot(time_slot)
    duration_minutes = SERVICE_DURATIONS.get(service, 60)

    # Create a datetime to add duration
    today = date.today()
    start_datetime = datetime.combine(today, start_time)
    end_datetime = start_datetime + timedelta(minutes=duration_minutes)

    # Format back to 12-hour time
    return end_datetime.strftime("%-I:%M %p")


def get_service_display_name(service: ExpressService) -> str:
    """Returns the human-readable display name for a service."""
    return SERVICE_DISPLAY_NAMES.get(service, service.value)


async def check_slot_availability(
    existing_appointments: List,
    time_slot: str
) -> Tuple[bool, Optional[str]]:
    """
    Checks if a time slot is available (no double-booking).

    Args:
        existing_appointments: List of appointments for the target date
        time_slot: The requested time slot

    Returns:
        Tuple of (is_available, reason_if_unavailable)
    """
    for appt in existing_appointments:
        if appt.time_slot == time_slot and appt.status != AppointmentStatus.CANCELLED.value:
            return False, f"This time slot ({time_slot}) is already booked"

    return True, None


def get_available_slots_for_date(
    appointment_date: date,
    existing_appointments: List
) -> List[AvailableSlot]:
    """
    Returns all time slots with availability status for a given date.

    Args:
        appointment_date: The date to check
        existing_appointments: List of existing appointments for that date

    Returns:
        List of AvailableSlot objects
    """
    slots = []
    today = get_bangkok_date()
    now = get_bangkok_now()

    # Get booked slots (non-cancelled)
    booked_slots = {
        appt.time_slot for appt in existing_appointments
        if appt.status != AppointmentStatus.CANCELLED.value
    }

    for time_slot in VALID_TIME_SLOTS:
        available = True
        reason = None

        # Check if slot is already booked
        if time_slot in booked_slots:
            available = False
            reason = "Already booked"
        # For same-day, check if time has passed
        elif appointment_date == today:
            slot_time = parse_time_slot(time_slot)
            slot_datetime = datetime.combine(today, slot_time, tzinfo=BANGKOK_TZ)
            if slot_datetime <= now:
                available = False
                reason = "Time has passed"

        slots.append(AvailableSlot(
            time_slot=time_slot,
            available=available,
            reason=reason
        ))

    return slots


def send_customer_confirmation_email(
    customer_name: str,
    customer_email: str,
    booking_reference: str,
    appointment_date: date,
    time_slot: str,
    service: ExpressService,
    garment_details: Optional[str],
    special_requests: Optional[str]
) -> bool:
    """
    Sends confirmation email to the customer.

    Returns:
        True if email sent successfully, False otherwise
    """
    service_name = get_service_display_name(service)

    # Plain text email body
    text_body = f"""
Dear {customer_name},

Thank you for booking with {BUSINESS_NAME}!

Your appointment has been received and is pending confirmation. Here are your booking details:

===========================================
BOOKING CONFIRMATION
===========================================

Booking Reference: {booking_reference}
Status: Pending Confirmation

APPOINTMENT DETAILS:
- Date: {appointment_date.strftime('%A, %B %d, %Y')}
- Time: {time_slot}
- Service: {service_name}

GARMENT DETAILS:
{garment_details or 'Not specified'}

SPECIAL REQUESTS:
{special_requests or 'None'}

===========================================

WHAT'S NEXT?
Our team will review your booking and confirm within 24 hours.
You will receive another email once your appointment is confirmed.

LOCATION:
{BUSINESS_NAME}
{BUSINESS_ADDRESS}

If you need to make changes or have questions, please contact us:
Phone: {BUSINESS_PHONE}
Email: {BUSINESS_EMAIL}

We look forward to serving you!

Best regards,
{BUSINESS_NAME} Team

---
This is an automated message. Please save your booking reference: {booking_reference}
"""

    # HTML email body
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #1a365d; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background: #f9f9f9; }}
        .booking-ref {{ background: #2d3748; color: white; padding: 15px; text-align: center; font-size: 24px; letter-spacing: 2px; margin: 20px 0; }}
        .details-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        .details-table td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
        .details-table td:first-child {{ font-weight: bold; width: 40%; color: #555; }}
        .status-pending {{ color: #d69e2e; font-weight: bold; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
        .cta {{ background: #2b6cb0; color: white; padding: 12px 25px; text-decoration: none; display: inline-block; margin: 10px 0; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{BUSINESS_NAME}</h1>
            <p>Express Tailoring Services</p>
        </div>

        <div class="content">
            <h2>Booking Received!</h2>
            <p>Dear {customer_name},</p>
            <p>Thank you for choosing {BUSINESS_NAME}. Your appointment request has been received.</p>

            <div class="booking-ref">
                {booking_reference}
            </div>
            <p style="text-align: center;"><span class="status-pending">⏳ Pending Confirmation</span></p>

            <h3>Appointment Details</h3>
            <table class="details-table">
                <tr>
                    <td>Date</td>
                    <td>{appointment_date.strftime('%A, %B %d, %Y')}</td>
                </tr>
                <tr>
                    <td>Time</td>
                    <td>{time_slot}</td>
                </tr>
                <tr>
                    <td>Service</td>
                    <td>{service_name}</td>
                </tr>
                <tr>
                    <td>Garment Details</td>
                    <td>{garment_details or '<em>Not specified</em>'}</td>
                </tr>
                <tr>
                    <td>Special Requests</td>
                    <td>{special_requests or '<em>None</em>'}</td>
                </tr>
            </table>

            <h3>What's Next?</h3>
            <p>Our team will review your booking and confirm within 24 hours. You will receive a confirmation email once approved.</p>

            <h3>Location</h3>
            <p>
                <strong>{BUSINESS_NAME}</strong><br>
                {BUSINESS_ADDRESS}<br>
                Phone: {BUSINESS_PHONE}<br>
                Email: {BUSINESS_EMAIL}
            </p>
        </div>

        <div class="footer">
            <p>This is an automated message from {BUSINESS_NAME}</p>
            <p>Please save your booking reference: <strong>{booking_reference}</strong></p>
        </div>
    </div>
</body>
</html>
"""

    try:
        email_service.send_email(
            to_emails=[customer_email],
            subject=f"Booking Received - {BUSINESS_NAME} [{booking_reference}]",
            body=text_body,
            html_body=html_body
        )
        return True
    except Exception as e:
        print(f"Failed to send customer confirmation email: {e}")
        return False


def send_business_notification_email(
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    booking_reference: str,
    appointment_date: date,
    time_slot: str,
    service: ExpressService,
    garment_details: Optional[str],
    special_requests: Optional[str]
) -> bool:
    """
    Sends notification email to the business owner about new booking.

    Returns:
        True if email sent successfully, False otherwise
    """
    service_name = get_service_display_name(service)

    text_body = f"""
NEW APPOINTMENT BOOKING

Booking Reference: {booking_reference}

CUSTOMER INFORMATION:
- Name: {customer_name}
- Email: {customer_email}
- Phone: {customer_phone}

APPOINTMENT DETAILS:
- Date: {appointment_date.strftime('%A, %B %d, %Y')}
- Time: {time_slot}
- Service: {service_name}

GARMENT DETAILS:
{garment_details or 'Not specified'}

SPECIAL REQUESTS:
{special_requests or 'None'}

---
Action Required: Please confirm or reschedule this appointment.
"""

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
        .alert {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 15px 0; }}
        .details {{ background: #f3f4f6; padding: 15px; margin: 10px 0; }}
        .label {{ font-weight: bold; color: #374151; }}
    </style>
</head>
<body>
    <h2>🗓️ New Appointment Booking</h2>

    <div class="alert">
        <strong>Booking Reference:</strong> {booking_reference}<br>
        <strong>Status:</strong> Pending Confirmation
    </div>

    <h3>Customer Information</h3>
    <div class="details">
        <p><span class="label">Name:</span> {customer_name}</p>
        <p><span class="label">Email:</span> <a href="mailto:{customer_email}">{customer_email}</a></p>
        <p><span class="label">Phone:</span> <a href="tel:{customer_phone}">{customer_phone}</a></p>
    </div>

    <h3>Appointment Details</h3>
    <div class="details">
        <p><span class="label">Date:</span> {appointment_date.strftime('%A, %B %d, %Y')}</p>
        <p><span class="label">Time:</span> {time_slot}</p>
        <p><span class="label">Service:</span> {service_name}</p>
    </div>

    <h3>Garment Details</h3>
    <div class="details">
        <p>{garment_details or '<em>Not specified</em>'}</p>
    </div>

    <h3>Special Requests</h3>
    <div class="details">
        <p>{special_requests or '<em>None</em>'}</p>
    </div>

    <p><strong>Action Required:</strong> Please confirm or reschedule this appointment via the admin dashboard.</p>
</body>
</html>
"""

    try:
        email_service.send_email(
            to_emails=[BUSINESS_EMAIL],
            subject=f"🗓️ New Booking: {customer_name} - {appointment_date.strftime('%b %d')} at {time_slot} [{booking_reference}]",
            body=text_body,
            html_body=html_body
        )
        return True
    except Exception as e:
        print(f"Failed to send business notification email: {e}")
        return False


def send_confirmation_status_email(
    customer_name: str,
    customer_email: str,
    booking_reference: str,
    appointment_date: date,
    time_slot: str,
    service: ExpressService,
    status: str,
    admin_notes: Optional[str] = None
) -> bool:
    """
    Sends email to customer when appointment is confirmed or cancelled.

    Returns:
        True if email sent successfully, False otherwise
    """
    service_name = get_service_display_name(service)

    if status == AppointmentStatus.CONFIRMED.value:
        subject = f"✅ Appointment Confirmed - {BUSINESS_NAME} [{booking_reference}]"
        status_text = "CONFIRMED"
        status_color = "#38a169"
        status_emoji = "✅"
        message = "Great news! Your appointment has been confirmed."
    else:  # CANCELLED
        subject = f"❌ Appointment Cancelled - {BUSINESS_NAME} [{booking_reference}]"
        status_text = "CANCELLED"
        status_color = "#e53e3e"
        status_emoji = "❌"
        message = "We're sorry, but your appointment has been cancelled."

    notes_section = ""
    if admin_notes:
        notes_section = f"""
<h3>Notes from {BUSINESS_NAME}:</h3>
<div class="details">
    <p>{admin_notes}</p>
</div>
"""

    text_body = f"""
Dear {customer_name},

{message}

Booking Reference: {booking_reference}
Status: {status_text}

APPOINTMENT DETAILS:
- Date: {appointment_date.strftime('%A, %B %d, %Y')}
- Time: {time_slot}
- Service: {service_name}

{f"Notes: {admin_notes}" if admin_notes else ""}

If you have any questions, please contact us:
Phone: {BUSINESS_PHONE}
Email: {BUSINESS_EMAIL}

Best regards,
{BUSINESS_NAME} Team
"""

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #1a365d; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background: #f9f9f9; }}
        .status {{ background: {status_color}; color: white; padding: 15px; text-align: center; font-size: 20px; margin: 20px 0; border-radius: 5px; }}
        .details {{ background: white; padding: 15px; margin: 10px 0; border: 1px solid #ddd; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{BUSINESS_NAME}</h1>
        </div>

        <div class="content">
            <p>Dear {customer_name},</p>
            <p>{message}</p>

            <div class="status">
                {status_emoji} {status_text}
            </div>

            <p><strong>Booking Reference:</strong> {booking_reference}</p>

            <h3>Appointment Details</h3>
            <div class="details">
                <p><strong>Date:</strong> {appointment_date.strftime('%A, %B %d, %Y')}</p>
                <p><strong>Time:</strong> {time_slot}</p>
                <p><strong>Service:</strong> {service_name}</p>
            </div>

            {notes_section}

            <h3>Contact Us</h3>
            <p>
                Phone: {BUSINESS_PHONE}<br>
                Email: {BUSINESS_EMAIL}
            </p>
        </div>

        <div class="footer">
            <p>Thank you for choosing {BUSINESS_NAME}</p>
        </div>
    </div>
</body>
</html>
"""

    try:
        email_service.send_email(
            to_emails=[customer_email],
            subject=subject,
            body=text_body,
            html_body=html_body
        )
        return True
    except Exception as e:
        print(f"Failed to send status update email: {e}")
        return False
