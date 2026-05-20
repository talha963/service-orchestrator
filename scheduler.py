"""
Scheduling Intelligence — Prevents double bookings, manages time slots,
travel buffers, waitlists, and auto-rescheduling.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from trace_logger import log_trace

logger = logging.getLogger("orchestrator.scheduler")

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_FILE = BASE_DIR / "data" / "bookings_db.json"


def _load_bookings() -> list[dict]:
    try:
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_bookings(bookings: list[dict]):
    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, indent=2, default=str)


def _parse_time_slot(slot: str) -> tuple[int, int]:
    """Parse '08:00-12:00' into (8, 12) hours."""
    parts = slot.split("-")
    start = int(parts[0].split(":")[0])
    end = int(parts[1].split(":")[0])
    return start, end


def _day_name(date: datetime) -> str:
    """Get lowercase day name from a datetime."""
    return date.strftime("%A").lower()


def check_provider_availability(
    provider: dict,
    requested_date: datetime,
    requested_hour: int,
    duration_hours: int = 1,
) -> dict:
    """
    Check if a provider is available at the requested date/time.
    Returns {"available": bool, "reason": str, "alternate_slots": [...]}
    """
    day = _day_name(requested_date)
    day_slots = provider.get("availability", {}).get(day, [])

    # Check if provider works on this day
    if not day_slots:
        alternates = _find_alternate_slots(provider, requested_date, requested_hour)
        reason = f"{provider['name']} does not work on {day}s."
        log_trace(
            stage="scheduling_check",
            input_data={"provider": provider["name"], "date": str(requested_date), "hour": requested_hour},
            reasoning=reason,
            confidence=100,
            output_data={"available": False, "alternate_slots": alternates},
        )
        return {"available": False, "reason": reason, "alternate_slots": alternates}

    # Check if requested hour falls within any working slot
    in_slot = False
    for slot in day_slots:
        start, end = _parse_time_slot(slot)
        if start <= requested_hour < end and requested_hour + duration_hours <= end:
            in_slot = True
            break

    if not in_slot:
        alternates = _find_alternate_slots(provider, requested_date, requested_hour)
        reason = f"{provider['name']} is not available at {requested_hour}:00 on {day}. Working hours: {day_slots}"
        log_trace(
            stage="scheduling_check",
            input_data={"provider": provider["name"], "date": str(requested_date), "hour": requested_hour},
            reasoning=reason,
            confidence=100,
            output_data={"available": False, "alternate_slots": alternates},
        )
        return {"available": False, "reason": reason, "alternate_slots": alternates}

    # Check capacity
    if provider.get("current_load", 0) >= provider.get("capacity_per_day", 4):
        alternates = _find_alternate_slots(provider, requested_date, requested_hour)
        reason = f"{provider['name']} has reached maximum capacity ({provider['capacity_per_day']} jobs) for today."
        log_trace(
            stage="scheduling_check",
            input_data={"provider": provider["name"], "date": str(requested_date), "hour": requested_hour},
            reasoning=reason,
            confidence=100,
            output_data={"available": False, "alternate_slots": alternates},
        )
        return {"available": False, "reason": reason, "alternate_slots": alternates}

    # Check for double booking
    bookings = _load_bookings()
    for booking in bookings:
        if (
            booking.get("provider_id") == provider["id"]
            and booking.get("status") in ("confirmed", "in_progress")
            and booking.get("scheduled_date") == requested_date.strftime("%Y-%m-%d")
        ):
            booked_hour = booking.get("scheduled_hour", -1)
            # Check overlap with travel buffer (1 hour buffer)
            if abs(booked_hour - requested_hour) < duration_hours + 1:
                alternates = _find_alternate_slots(provider, requested_date, requested_hour)
                reason = (
                    f"{provider['name']} has a conflicting booking at {booked_hour}:00 "
                    f"(with 1hr travel buffer). Next available slots suggested."
                )
                log_trace(
                    stage="scheduling_conflict",
                    input_data={
                        "provider": provider["name"],
                        "requested": f"{requested_hour}:00",
                        "conflict": f"{booked_hour}:00",
                    },
                    reasoning=reason,
                    confidence=100,
                    output_data={"available": False, "alternate_slots": alternates},
                )
                return {"available": False, "reason": reason, "alternate_slots": alternates}

    # Provider is available!
    reason = f"{provider['name']} is available at {requested_hour}:00 on {day}."
    log_trace(
        stage="scheduling_check",
        input_data={"provider": provider["name"], "date": str(requested_date), "hour": requested_hour},
        reasoning=reason,
        confidence=95,
        output_data={"available": True},
    )
    return {"available": True, "reason": reason, "alternate_slots": []}


def _find_alternate_slots(
    provider: dict,
    requested_date: datetime,
    preferred_hour: int,
    days_ahead: int = 3,
) -> list[dict]:
    """Find up to 3 alternate available slots within the next few days."""
    alternates = []
    bookings = _load_bookings()

    for day_offset in range(0, days_ahead + 1):
        check_date = requested_date + timedelta(days=day_offset)
        day = _day_name(check_date)
        day_slots = provider.get("availability", {}).get(day, [])

        for slot in day_slots:
            start, end = _parse_time_slot(slot)
            for hour in range(start, end):
                # Skip if it's the same date/time that was already rejected
                if day_offset == 0 and hour == preferred_hour:
                    continue

                # Check for existing bookings
                conflict = False
                for booking in bookings:
                    if (
                        booking.get("provider_id") == provider["id"]
                        and booking.get("status") in ("confirmed", "in_progress")
                        and booking.get("scheduled_date") == check_date.strftime("%Y-%m-%d")
                        and abs(booking.get("scheduled_hour", -1) - hour) < 2
                    ):
                        conflict = True
                        break

                if not conflict:
                    alternates.append({
                        "date": check_date.strftime("%Y-%m-%d"),
                        "day": day,
                        "time": f"{hour:02d}:00",
                        "provider": provider["name"],
                    })
                    if len(alternates) >= 3:
                        return alternates

    return alternates


def resolve_time_preference(time_pref: str, date_pref: str) -> tuple[datetime, int]:
    """
    Convert natural language time/date preferences to datetime + hour.
    Returns (date, hour).
    """
    now = datetime.now(timezone.utc)

    # Parse date
    date_lower = date_pref.lower() if date_pref else "today"
    if date_lower in ("today", "aaj", "abhi"):
        target_date = now
    elif date_lower in ("tomorrow", "kal", "tmrw"):
        target_date = now + timedelta(days=1)
    elif date_lower in ("day after tomorrow", "parson"):
        target_date = now + timedelta(days=2)
    else:
        target_date = now + timedelta(days=1)  # Default to tomorrow

    # Parse time
    time_lower = time_pref.lower() if time_pref else "morning"
    explicit_ampm = re.search(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", time_lower)
    explicit_24h = re.search(r"\b([01]?\d|2[0-3]):?([0-5]\d)?\b", time_lower)

    if explicit_ampm:
        hour = int(explicit_ampm.group(1))
        if explicit_ampm.group(2) == "pm" and hour != 12:
            hour += 12
        elif explicit_ampm.group(2) == "am" and hour == 12:
            hour = 0
    elif explicit_24h:
        hour = int(explicit_24h.group(1))
    elif any(w in time_lower for w in ("morning", "subah", "subh")):
        hour = 10
    elif any(w in time_lower for w in ("afternoon", "dopahar", "dopehar")):
        hour = 14
    elif any(w in time_lower for w in ("evening", "shaam", "sham")):
        hour = 17
    elif any(w in time_lower for w in ("night", "raat")):
        hour = 20
    elif any(w in time_lower for w in ("asap", "foran", "abhi", "now", "jaldi")):
        hour = max(now.hour + 1, 8)  # At least 1 hour from now, min 8 AM
    else:
        hour = 10  # Default morning

    log_trace(
        stage="time_resolution",
        input_data={"time_preference": time_pref, "date_preference": date_pref},
        reasoning=f"Resolved '{date_pref} {time_pref}' to {target_date.strftime('%Y-%m-%d')} at {hour:02d}:00",
        confidence=85,
        output_data={"date": target_date.strftime("%Y-%m-%d"), "hour": hour},
    )

    return target_date, hour


def auto_reschedule(booking_id: str, providers: list[dict]) -> dict | None:
    """
    Auto-reschedule when a provider cancels.
    Finds the next best available provider for the same service/time.
    """
    bookings = _load_bookings()
    target_booking = None

    for b in bookings:
        if b.get("booking_id") == booking_id:
            target_booking = b
            break

    if not target_booking:
        return None

    cancelled_provider_id = target_booking.get("provider_id")
    service_type = target_booking.get("service_type", "")
    scheduled_date_str = target_booking.get("scheduled_date", "")
    scheduled_hour = target_booking.get("scheduled_hour", 10)

    try:
        scheduled_date = datetime.strptime(scheduled_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        scheduled_date = datetime.now(timezone.utc) + timedelta(days=1)

    # Find alternate providers
    candidates = [
        p for p in providers
        if p["service"].lower() == service_type.lower() and p["id"] != cancelled_provider_id
    ]

    for candidate in sorted(candidates, key=lambda x: x.get("rating", 0), reverse=True):
        avail = check_provider_availability(candidate, scheduled_date, scheduled_hour)
        if avail["available"]:
            old_provider_name = target_booking.get("provider_name", "Previous provider")
            target_booking["rescheduled_from_provider_id"] = cancelled_provider_id
            target_booking["provider_id"] = candidate["id"]
            target_booking["provider_name"] = candidate["name"]
            target_booking["status"] = "confirmed"
            target_booking["updated_at"] = datetime.now(timezone.utc).isoformat()
            target_booking.pop("cancelled_by", None)
            target_booking.setdefault("notifications", []).append({
                "type": "sms",
                "recipient": "user",
                "message": (
                    f"Booking {booking_id} was rescheduled from {old_provider_name} "
                    f"to {candidate['name']} at {scheduled_hour:02d}:00."
                ),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "delivered",
            })
            _save_bookings(bookings)

            log_trace(
                stage="auto_reschedule",
                input_data={"booking_id": booking_id, "cancelled_provider": cancelled_provider_id},
                reasoning=(
                    f"Provider cancelled booking {booking_id}. "
                    f"Auto-rescheduled to {candidate['name']} (rating: {candidate['rating']}) "
                    f"at the same time slot."
                ),
                confidence=90,
                output_data={"new_provider": candidate["name"], "new_provider_id": candidate["id"]},
                metadata={"booking_id": booking_id},
            )
            return {
                "rescheduled": True,
                "new_provider": candidate,
                "time": f"{scheduled_hour:02d}:00",
                "date": scheduled_date_str,
                "booking": target_booking,
            }

    log_trace(
        stage="auto_reschedule",
        input_data={"booking_id": booking_id},
        reasoning=f"No alternate provider available for booking {booking_id} at the same time. Suggesting alternate slots.",
        confidence=60,
        metadata={"booking_id": booking_id},
    )
    return {"rescheduled": False, "reason": "No alternate provider available at the requested time."}
