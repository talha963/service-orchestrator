"""
Dispute & Escalation Handler — Manages no-shows, cancellations,
quality complaints, price disagreements, refunds, and escalations.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from openai import AsyncOpenAI
from trace_logger import log_trace
from booking_engine import update_booking_status, get_booking

logger = logging.getLogger("orchestrator.dispute")


class DisputeTypes:
    NO_SHOW = "no_show"
    LATE_ARRIVAL = "late_arrival"
    QUALITY_COMPLAINT = "quality_complaint"
    PRICE_DISAGREEMENT = "price_disagreement"
    SERVICE_OVERRUN = "service_overrun"
    CANCELLATION = "cancellation"
    OTHER = "other"


# Automatic resolution policies
RESOLUTION_POLICIES = {
    DisputeTypes.NO_SHOW: {
        "auto_refund": True,
        "refund_percentage": 100,
        "provider_penalty": "warning",
        "penalty_threshold": 3,  # Auto-suspend after 3 no-shows
        "action": "Full refund issued. Provider receives warning. Auto-reschedule offered.",
    },
    DisputeTypes.LATE_ARRIVAL: {
        "auto_refund": True,
        "refund_percentage": 15,  # 15% discount for late arrival
        "provider_penalty": "none",
        "action": "15% discount applied for inconvenience. Provider on-time score reduced.",
    },
    DisputeTypes.QUALITY_COMPLAINT: {
        "auto_refund": False,  # Needs AI assessment
        "refund_percentage": 0,
        "provider_penalty": "review",
        "action": "Complaint under AI review. Evidence assessment in progress.",
    },
    DisputeTypes.PRICE_DISAGREEMENT: {
        "auto_refund": False,
        "refund_percentage": 0,
        "provider_penalty": "none",
        "action": "Original price breakdown shared. Mediation offered.",
    },
    DisputeTypes.SERVICE_OVERRUN: {
        "auto_refund": True,
        "refund_percentage": 10,
        "provider_penalty": "none",
        "action": "10% compensation for time overrun. Provider notified.",
    },
    DisputeTypes.CANCELLATION: {
        "auto_refund": True,
        "refund_percentage": 100,
        "provider_penalty": "warning",
        "action": "Full refund issued. Auto-reschedule triggered.",
    },
}


async def handle_dispute(
    client: AsyncOpenAI,
    model: str,
    booking_id: str,
    dispute_type: str,
    description: str,
    evidence_urls: list[str] | None = None,
) -> dict:
    """
    Handle a dispute with automatic resolution or AI-assisted assessment.
    """
    booking = get_booking(booking_id)
    if not booking:
        return {"error": f"Booking {booking_id} not found"}

    policy = RESOLUTION_POLICIES.get(dispute_type, RESOLUTION_POLICIES[DisputeTypes.OTHER] if DisputeTypes.OTHER in RESOLUTION_POLICIES else {
        "auto_refund": False, "refund_percentage": 0, "provider_penalty": "review",
        "action": "Dispute filed for manual review."
    })

    # Build dispute record
    dispute = {
        "dispute_id": f"DSP-{booking_id}",
        "booking_id": booking_id,
        "type": dispute_type,
        "description": description,
        "evidence_urls": evidence_urls or [],
        "status": "open",
        "resolution": None,
        "refund_amount": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Auto-resolve simple cases
    if policy.get("auto_refund"):
        refund_pct = policy["refund_percentage"]
        refund_amount = int(booking.get("price_total", 0) * refund_pct / 100)
        dispute["refund_amount"] = refund_amount
        dispute["status"] = "resolved"
        dispute["resolution"] = {
            "type": "automatic",
            "action": policy["action"],
            "refund_amount": refund_amount,
            "refund_percentage": refund_pct,
            "provider_penalty": policy.get("provider_penalty", "none"),
        }

        log_trace(
            stage="dispute_auto_resolution",
            input_data={"booking_id": booking_id, "dispute_type": dispute_type, "description": description},
            reasoning=(
                f"Dispute type '{dispute_type}' for booking {booking_id}. "
                f"Auto-resolution applied: {policy['action']} "
                f"Refund: Rs. {refund_amount} ({refund_pct}% of Rs. {booking.get('price_total', 0)}). "
                f"Provider penalty: {policy.get('provider_penalty', 'none')}."
            ),
            confidence=95,
            output_data=dispute,
            metadata={"booking_id": booking_id},
        )

    # AI-assisted assessment for complex cases
    elif dispute_type == DisputeTypes.QUALITY_COMPLAINT:
        ai_assessment = await _ai_assess_quality_complaint(
            client, model, booking, description, evidence_urls
        )
        dispute["ai_assessment"] = ai_assessment
        dispute["status"] = ai_assessment.get("recommended_status", "under_review")
        dispute["resolution"] = ai_assessment.get("resolution")
        dispute["refund_amount"] = ai_assessment.get("refund_amount", 0)

    elif dispute_type == DisputeTypes.PRICE_DISAGREEMENT:
        ai_mediation = await _ai_mediate_price(client, model, booking, description)
        dispute["ai_mediation"] = ai_mediation
        dispute["status"] = "mediated"
        dispute["resolution"] = ai_mediation

    else:
        # Escalate to human review
        dispute["status"] = "escalated"
        dispute["resolution"] = {
            "type": "human_escalation",
            "action": "Dispute has been escalated to human support team for review.",
            "reason": f"Dispute type '{dispute_type}' requires manual assessment.",
        }
        log_trace(
            stage="dispute_escalation",
            input_data={"booking_id": booking_id, "dispute_type": dispute_type},
            reasoning=(
                f"Dispute for booking {booking_id} escalated to human review. "
                f"AI confidence too low for automatic resolution of type '{dispute_type}'."
            ),
            confidence=40,
            metadata={"booking_id": booking_id},
        )

    # Update booking with dispute info
    update_booking_status(booking_id, "disputed", {"dispute": dispute})

    # Check if provider should be blacklisted
    blacklist_check = _check_blacklist(booking.get("provider_id", ""), dispute_type)
    if blacklist_check["should_blacklist"]:
        dispute["blacklist_action"] = blacklist_check

    return dispute


async def _ai_assess_quality_complaint(
    client: AsyncOpenAI,
    model: str,
    booking: dict,
    complaint: str,
    evidence_urls: list[str] | None,
) -> dict:
    """Use Antigravity LLM to assess quality complaint severity."""
    prompt = f"""Assess this service quality complaint:

Booking: {booking.get('booking_id')}
Service: {booking.get('service_type')}
Provider: {booking.get('provider_name')}
Price paid: Rs. {booking.get('price_total')}
Complaint: {complaint}
Evidence provided: {'Yes' if evidence_urls else 'No'}

Based on the complaint severity, recommend:
1. "severity": "low" / "medium" / "high"
2. "refund_percentage": 0-100
3. "recommended_status": "resolved" / "under_review"
4. "explanation": Why this decision was made
5. "provider_action": What action to take with the provider

Return ONLY valid JSON."""

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an AI dispute resolution expert. Be fair to both customer and provider."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        assessment = json.loads(content)

        refund_pct = assessment.get("refund_percentage", 0)
        refund_amount = int(booking.get("price_total", 0) * refund_pct / 100)

        result = {
            "severity": assessment.get("severity", "medium"),
            "refund_amount": refund_amount,
            "refund_percentage": refund_pct,
            "recommended_status": assessment.get("recommended_status", "under_review"),
            "explanation": assessment.get("explanation", ""),
            "provider_action": assessment.get("provider_action", "Under review"),
            "resolution": {
                "type": "ai_assessed",
                "action": assessment.get("explanation", "Quality complaint assessed by AI"),
                "refund_amount": refund_amount,
            },
        }

        log_trace(
            stage="dispute_ai_assessment",
            input_data={"booking_id": booking.get("booking_id"), "complaint": complaint},
            reasoning=(
                f"AI quality assessment: Severity={assessment.get('severity')}. "
                f"Recommended refund: {refund_pct}% (Rs. {refund_amount}). "
                f"Explanation: {assessment.get('explanation', 'N/A')}"
            ),
            confidence=75,
            output_data=result,
            metadata={"booking_id": booking.get("booking_id")},
        )

        return result

    except Exception as e:
        logger.error(f"AI assessment failed: {e}")
        return {
            "severity": "unknown",
            "recommended_status": "escalated",
            "explanation": "AI assessment failed. Escalating to human review.",
            "resolution": {"type": "human_escalation", "action": "Manual review required."},
        }


async def _ai_mediate_price(
    client: AsyncOpenAI,
    model: str,
    booking: dict,
    complaint: str,
) -> dict:
    """AI-mediated price disagreement resolution."""
    price_breakdown = booking.get("price_breakdown", {})

    prompt = f"""A customer is disputing the price for this service:

Service: {booking.get('service_type')}
Provider: {booking.get('provider_name')}
Total charged: Rs. {booking.get('price_total')}
Price breakdown: {json.dumps(price_breakdown)}
Customer complaint: {complaint}

Assess whether the price is fair and recommend resolution:
1. "is_fair": true/false
2. "explanation": Detailed explanation of price fairness
3. "recommended_adjustment": Amount to adjust (0 if fair)
4. "mediation_note": Message to both parties

Return ONLY valid JSON."""

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a fair price mediator. Consider both customer and provider perspectives."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        mediation = json.loads(content)

        result = {
            "type": "ai_mediation",
            "is_fair": mediation.get("is_fair", True),
            "explanation": mediation.get("explanation", ""),
            "recommended_adjustment": mediation.get("recommended_adjustment", 0),
            "mediation_note": mediation.get("mediation_note", ""),
            "original_breakdown": price_breakdown,
        }

        log_trace(
            stage="dispute_price_mediation",
            input_data={"booking_id": booking.get("booking_id"), "complaint": complaint},
            reasoning=(
                f"Price mediation: {'Fair' if mediation.get('is_fair') else 'Adjustment recommended'}. "
                f"Adjustment: Rs. {mediation.get('recommended_adjustment', 0)}. "
                f"{mediation.get('explanation', '')}"
            ),
            confidence=80,
            output_data=result,
            metadata={"booking_id": booking.get("booking_id")},
        )

        return result

    except Exception as e:
        logger.error(f"Price mediation failed: {e}")
        return {
            "type": "human_escalation",
            "action": "Price mediation failed. Escalated to human review.",
        }


def _check_blacklist(provider_id: str, dispute_type: str) -> dict:
    """Check if provider should be blacklisted based on dispute history."""
    # Count recent disputes for this provider
    from booking_engine import _load_bookings
    bookings = _load_bookings()

    provider_disputes = []
    for b in bookings:
        if b.get("provider_id") == provider_id and b.get("dispute"):
            provider_disputes.append(b["dispute"])

    no_show_count = sum(1 for d in provider_disputes if d.get("type") == DisputeTypes.NO_SHOW)
    total_disputes = len(provider_disputes)

    should_blacklist = no_show_count >= 3 or total_disputes >= 5

    result = {
        "should_blacklist": should_blacklist,
        "no_show_count": no_show_count,
        "total_disputes": total_disputes,
        "action": "SUSPENDED" if should_blacklist else "Active",
        "reason": (
            f"Provider has {no_show_count} no-shows and {total_disputes} total disputes"
            if should_blacklist else "Within acceptable threshold"
        ),
    }

    if should_blacklist:
        log_trace(
            stage="provider_blacklist",
            input_data={"provider_id": provider_id},
            reasoning=(
                f"BLACKLIST TRIGGERED: Provider {provider_id} suspended. "
                f"{no_show_count} no-shows, {total_disputes} total disputes exceed threshold."
            ),
            confidence=100,
        )

    return result
