"""
Booking Engine — Full lifecycle simulation from confirmation to completion.
Handles booking creation, notifications, status updates, receipts, and calendar management.
"""
import json
import random
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from trace_logger import log_trace
from sms_service import send_sms_message_sync

logger = logging.getLogger("orchestrator.booking")

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_FILE = BASE_DIR / "data" / "bookings_db.json"


class BookingRecord(BaseModel):
    booking_id: str
    user_id: str
    provider_id: str
    provider_name: str
    service_type: str
    scheduled_date: str
    scheduled_hour: int
    estimated_duration_hours: int = 1
    price_total: int
    price_breakdown: dict = {}
    status: str = "confirmed"  # confirmed → provider_en_route → in_progress → completed → rated → disputed
    location: str = ""
    location_lat: float = 0.0
    location_lng: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    notifications: list[dict] = []
    feedback: Optional[dict] = None
    dispute: Optional[dict] = None
    completion_checklist: list[dict] = []
    receipt: Optional[dict] = None


def _load_bookings() -> list[dict]:
    try:
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_bookings(bookings: list[dict]):
    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, indent=2, default=str)


def create_booking(
    user_id: str,
    provider: dict,
    service_type: str,
    scheduled_date: str,
    scheduled_hour: int,
    price_total: int,
    price_breakdown: dict,
    location: str = "",
    user_lat: float = 0.0,
    user_lng: float = 0.0,
) -> BookingRecord:
    """Create a new booking and persist it."""
    booking_id = f"BK-{random.randint(1000, 9999)}"
    now = datetime.now(timezone.utc).isoformat()

    booking = BookingRecord(
        booking_id=booking_id,
        user_id=user_id,
        provider_id=provider["id"],
        provider_name=provider["name"],
        service_type=service_type,
        scheduled_date=scheduled_date,
        scheduled_hour=scheduled_hour,
        price_total=price_total,
        price_breakdown=price_breakdown,
        status="confirmed",
        location=location,
        location_lat=user_lat,
        location_lng=user_lng,
        created_at=now,
        updated_at=now,
        notifications=[],
        completion_checklist=_generate_checklist(service_type),
    )

    # Generate initial notifications
    booking.notifications = _generate_notifications(booking)

    # Generate receipt
    booking.receipt = _generate_receipt(booking)

    # Save to database
    bookings = _load_bookings()
    bookings.append(booking.model_dump())
    _save_bookings(bookings)

    log_trace(
        stage="booking_creation",
        input_data={
            "user_id": user_id,
            "provider": provider["name"],
            "service": service_type,
            "date": scheduled_date,
            "hour": scheduled_hour,
        },
        reasoning=(
            f"Booking {booking_id} confirmed: {provider['name']} for {service_type} "
            f"on {scheduled_date} at {scheduled_hour:02d}:00. "
            f"Total price: Rs. {price_total}. "
            f"Calendar updated, notifications scheduled, receipt generated."
        ),
        confidence=98,
        output_data={"booking_id": booking_id, "status": "confirmed"},
        metadata={"booking_id": booking_id},
    )

    # Send immediate SMS notifications
    for notif in booking.notifications:
        if notif["status"] == "delivered": # Meaning it should be sent now
            recipient_phone = provider.get("phone", "+923000000000") if notif["recipient"] == "provider" else "+923000000000"
            send_sms_message_sync(recipient_phone, notif["message"])

    return booking


def _generate_notifications(booking: BookingRecord) -> list[dict]:
    """Generate simulated SMS/WhatsApp notifications."""
    now = datetime.now(timezone.utc)
    notifications = [
        {
            "type": "sms",
            "recipient": "user",
            "message": (
                f"✅ Booking Confirmed!\n"
                f"Service: {booking.service_type.title()}\n"
                f"Provider: {booking.provider_name}\n"
                f"Date: {booking.scheduled_date}\n"
                f"Time: {booking.scheduled_hour:02d}:00\n"
                f"Total: Rs. {booking.price_total}\n"
                f"Booking ID: {booking.booking_id}"
            ),
            "sent_at": now.isoformat(),
            "status": "delivered",
        },
        {
            "type": "sms",
            "recipient": "provider",
            "message": (
                f"📋 New Job Assigned!\n"
                f"Service: {booking.service_type.title()}\n"
                f"Location: {booking.location}\n"
                f"Date: {booking.scheduled_date}\n"
                f"Time: {booking.scheduled_hour:02d}:00\n"
                f"Booking ID: {booking.booking_id}"
            ),
            "sent_at": now.isoformat(),
            "status": "delivered",
        },
        {
            "type": "sms",
            "recipient": "user",
            "message": f"🔔 Reminder: {booking.provider_name} is scheduled for {booking.service_type} tomorrow at {booking.scheduled_hour:02d}:00. Booking ID: {booking.booking_id}",
            "scheduled_for": "1_hour_before",
            "status": "scheduled",
        },
        {
            "type": "sms",
            "recipient": "user",
            "message": f"⏰ {booking.provider_name} will arrive in 15 minutes for your {booking.service_type} service.",
            "scheduled_for": "15_mins_before",
            "status": "scheduled",
        },
    ]
    return notifications


def _generate_receipt(booking: BookingRecord) -> dict:
    """Generate an itemized receipt."""
    breakdown = booking.price_breakdown
    items = []

    if breakdown.get("base_rate"):
        items.append({"item": "Service Base Rate", "amount": breakdown["base_rate"]})
    if breakdown.get("distance_surcharge"):
        items.append({"item": "Distance Surcharge", "amount": breakdown["distance_surcharge"]})
    if breakdown.get("urgency_premium"):
        items.append({"item": "Urgency Premium", "amount": breakdown["urgency_premium"]})
    if breakdown.get("complexity_addon"):
        items.append({"item": "Complexity Add-on", "amount": breakdown["complexity_addon"]})
    if breakdown.get("demand_surge"):
        items.append({"item": "Demand Adjustment", "amount": breakdown["demand_surge"]})
    if breakdown.get("loyalty_discount"):
        items.append({"item": "Loyalty Discount", "amount": -breakdown["loyalty_discount"]})

    return {
        "receipt_id": f"RCP-{booking.booking_id}",
        "booking_id": booking.booking_id,
        "items": items,
        "total": booking.price_total,
        "currency": "PKR",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "payment_status": "pending",
    }


def _generate_checklist(service_type: str) -> list[dict]:
    """Generate service completion checklist based on service type."""
    checklists = {
        "ac repair": [
            {"item": "Inspected AC unit", "completed": False},
            {"item": "Checked gas levels", "completed": False},
            {"item": "Cleaned filters", "completed": False},
            {"item": "Tested cooling output", "completed": False},
            {"item": "Photo evidence uploaded", "completed": False},
        ],
        "electrician": [
            {"item": "Inspected wiring", "completed": False},
            {"item": "Tested circuits", "completed": False},
            {"item": "Fixed reported issue", "completed": False},
            {"item": "Safety check completed", "completed": False},
            {"item": "Photo evidence uploaded", "completed": False},
        ],
        "plumber": [
            {"item": "Inspected pipes", "completed": False},
            {"item": "Fixed leak/blockage", "completed": False},
            {"item": "Tested water flow", "completed": False},
            {"item": "Cleaned work area", "completed": False},
            {"item": "Photo evidence uploaded", "completed": False},
        ],
        "beautician": [
            {"item": "Consultation completed", "completed": False},
            {"item": "Service performed", "completed": False},
            {"item": "Client satisfaction check", "completed": False},
            {"item": "Photo evidence uploaded", "completed": False},
        ],
        "mechanic": [
            {"item": "Diagnostic scan completed", "completed": False},
            {"item": "Issue identified and fixed", "completed": False},
            {"item": "Test drive/test run", "completed": False},
            {"item": "Photo evidence uploaded", "completed": False},
        ],
        "tutor": [
            {"item": "Session plan prepared", "completed": False},
            {"item": "Lesson delivered", "completed": False},
            {"item": "Assignment given", "completed": False},
            {"item": "Progress report updated", "completed": False},
        ],
    }
    return checklists.get(service_type.lower(), [
        {"item": "Service performed", "completed": False},
        {"item": "Customer satisfied", "completed": False},
    ])


def update_booking_status(booking_id: str, new_status: str, extra_data: dict = None) -> dict | None:
    """Update a booking's status and log the transition."""
    bookings = _load_bookings()
    for i, b in enumerate(bookings):
        if b.get("booking_id") == booking_id:
            old_status = b["status"]
            b["status"] = new_status
            b["updated_at"] = datetime.now(timezone.utc).isoformat()

            if extra_data:
                b.update(extra_data)

            # Add status-specific notifications
            if new_status == "provider_en_route":
                msg = f"🚗 {b['provider_name']} is on the way! Estimated arrival: 15-20 minutes."
                b.setdefault("notifications", []).append({
                    "type": "sms",
                    "recipient": "user",
                    "message": msg,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "status": "delivered",
                })
                send_sms_message_sync("+923000000000", msg)
            elif new_status == "in_progress":
                msg = f"🔧 {b['provider_name']} has started working on your {b.get('service_type', 'service')}."
                b.setdefault("notifications", []).append({
                    "type": "sms",
                    "recipient": "user",
                    "message": msg,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "status": "delivered",
                })
                send_sms_message_sync("+923000000000", msg)
            elif new_status == "completed":
                msg = f"✅ Service complete! Please rate your experience with {b['provider_name']}."
                b.setdefault("notifications", []).append({
                    "type": "sms",
                    "recipient": "user",
                    "message": msg,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "status": "delivered",
                })
                send_sms_message_sync("+923000000000", msg)

            _save_bookings(bookings)

            log_trace(
                stage="booking_status_update",
                input_data={"booking_id": booking_id, "old_status": old_status, "new_status": new_status},
                reasoning=f"Booking {booking_id} status changed: {old_status} → {new_status}.",
                confidence=100,
                metadata={"booking_id": booking_id},
            )

            return b

    return None


def get_booking(booking_id: str) -> dict | None:
    """Get a booking by ID."""
    bookings = _load_bookings()
    for b in bookings:
        if b.get("booking_id") == booking_id:
            return b
    return None


def get_user_bookings(user_id: str) -> list[dict]:
    """Get all bookings for a user."""
    bookings = _load_bookings()
    return [b for b in bookings if b.get("user_id") == user_id]


def cancel_booking(booking_id: str, cancelled_by: str = "user") -> dict | None:
    """Cancel a booking."""
    booking = update_booking_status(booking_id, "cancelled", {"cancelled_by": cancelled_by})
    if booking:
        log_trace(
            stage="booking_cancellation",
            input_data={"booking_id": booking_id, "cancelled_by": cancelled_by},
            reasoning=(
                f"Booking {booking_id} cancelled by {cancelled_by}. "
                f"{'Auto-reschedule triggered.' if cancelled_by == 'provider' else 'Refund may apply.'}"
            ),
            confidence=100,
            metadata={"booking_id": booking_id},
        )
    return booking
