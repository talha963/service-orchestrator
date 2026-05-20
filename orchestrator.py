"""
Service Orchestrator — Antigravity Edition
Central agentic controller for the informal service economy platform.
Orchestrates: NLU → Matching → Scheduling → Pricing → Booking → Follow-up → Feedback → Disputes
"""
import json
import os
import logging
import requests as http_requests
from dotenv import load_dotenv
from pathlib import Path

# Load .env BEFORE any os.getenv() calls
load_dotenv()
from datetime import datetime, timedelta, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# Internal modules
from nlu_engine import extract_intent, normalize_location, generate_clarification, ExtractedIntent
from matcher import find_best_matches, MAPS_API_KEY
import matcher as matcher_module
from scheduler import check_provider_availability, resolve_time_preference, auto_reschedule
from pricing import calculate_price, estimate_demand_level, PriceBreakdown
from booking_engine import (
    create_booking, update_booking_status, get_booking, get_user_bookings, cancel_booking,
)
from quality_loop import process_feedback, get_provider_reputation
from dispute_handler import handle_dispute as process_dispute, DisputeTypes
from provider_optimizer import (
    get_workload_dashboard, get_demand_forecast, get_recommended_slots, get_fair_earning_analysis,
)
from stress_tests import get_scenario, list_scenarios, execute_scenario, execute_all_scenarios
from trace_logger import get_all_traces, get_recent_traces, get_traces_by_booking, clear_traces, log_trace

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent
MOBILE_DIR = BASE_DIR / "mobile"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Set Maps key in matcher
matcher_module.MAPS_API_KEY = GOOGLE_MAPS_KEY

# In-memory alert store
_alerts: list[dict] = []

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("orchestrator")

# --- DATA MODELS ---
class IncomingMessage(BaseModel):
    user_id: str
    message: str
    latitude: float = 0.0
    longitude: float = 0.0

class FeedbackPayload(BaseModel):
    rating: int = Field(ge=1, le=5)
    review_text: str = ""

class DisputePayload(BaseModel):
    dispute_type: str = "quality_complaint"
    description: str
    evidence_urls: list[str] = []

class CancelPayload(BaseModel):
    cancelled_by: str = "user"
    reason: str = ""

# --- APP SETUP ---
app = FastAPI(
    title="Service Orchestrator — Antigravity Edition",
    description="Agentic system for the informal service economy with full lifecycle management",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_client = AsyncOpenAI(api_key=GROQ_API_KEY or "missing", base_url="https://api.groq.com/openai/v1")


# ========================
# MAIN LIFECYCLE ENDPOINT
# ========================

@app.post("/webhook/message")
async def handle_request(payload: IncomingMessage):
    """
    Main Antigravity orchestration endpoint.
    Full lifecycle: NLU → Match → Schedule → Price → Book
    """
    log_trace(
        stage="request_received",
        input_data={"user_id": payload.user_id, "message": payload.message, "lat": payload.latitude, "lng": payload.longitude},
        reasoning=f"New service request from user '{payload.user_id}': '{payload.message}'",
        confidence=100,
    )

    # STEP 1: NLU — Understand the request
    intent = await extract_intent(openai_client, LLM_MODEL, payload.message)

    # Handle low confidence
    if intent.confidence_score < 70:
        clarifications = await generate_clarification(openai_client, LLM_MODEL, payload.message, intent)
        log_trace(
            stage="low_confidence_fallback",
            input_data={"confidence": intent.confidence_score},
            reasoning=f"Low confidence ({intent.confidence_score}%). Asking clarification questions.",
            confidence=intent.confidence_score,
        )
        return {
            "status": "clarification_needed",
            "intent": intent.model_dump(),
            "clarification_questions": clarifications,
            "trace_summary": f"Parsed with {intent.confidence_score}% confidence. Need more info.",
        }

    # STEP 2: Location Resolution
    user_lat, user_lng = payload.latitude, payload.longitude
    location_data = normalize_location(intent.location)
    if location_data:
        user_lat = location_data["lat"]
        user_lng = location_data["lng"]

    # STEP 3: Provider Matching
    match_result = find_best_matches(intent, user_lat, user_lng, top_n=3)
    if not match_result or not match_result[0]:
        return {
            "status": "no_provider_available",
            "intent": intent.model_dump(),
            "message": f"No providers found for '{intent.service_type}' in your area.",
            "suggestions": ["Try a different time slot", "Expand search radius", "Try a related service category"],
        }

    top_matches, all_scored = match_result
    best_match = top_matches[0]

    # Get the full provider data for the best match
    best_provider = all_scored[0]["provider"]

    # STEP 4: Scheduling
    target_date, target_hour = resolve_time_preference(intent.preferred_time, intent.preferred_date)
    availability = check_provider_availability(best_provider, target_date, target_hour)

    # If not available, try alternates
    assigned_provider = best_provider
    if not availability["available"]:
        # Try other top matches
        for i, alt_match in enumerate(top_matches[1:], 1):
            alt_provider = all_scored[i]["provider"]
            alt_avail = check_provider_availability(alt_provider, target_date, target_hour)
            if alt_avail["available"]:
                assigned_provider = alt_provider
                best_match = alt_match
                availability = alt_avail
                log_trace(
                    stage="scheduling_fallback",
                    input_data={"original": best_provider["name"], "fallback": alt_provider["name"]},
                    reasoning=f"Primary provider {best_provider['name']} unavailable. Falling back to {alt_provider['name']}.",
                    confidence=85,
                )
                break
        else:
            from matcher import fetch_real_providers_from_google, get_place_phone_number
            # No platform slots are available at requested time. Let's fallback to Google Places (scraped data)
            places = fetch_real_providers_from_google(user_lat, user_lng, intent.service_type, radius=5000)
            
            google_providers = []
            if places:
                for p in places[:5]:
                    phone = None
                    place_id = p.get("place_id", "")
                    if place_id:
                        phone = get_place_phone_number(place_id)
                    google_providers.append({
                        "name": p["name"],
                        "address": p.get("address", ""),
                        "distance_km": p["distance_km"],
                        "rating": p.get("rating"),
                        "review_count": p.get("review_count", 0),
                        "is_open": p.get("is_open"),
                        "place_id": place_id,
                        "phone": phone,
                        "lat": p.get("lat"),
                        "lng": p.get("lng"),
                        "service": intent.service_type,
                    })

            log_trace(
                stage="no_slots_fallback_google_places",
                input_data={"service": intent.service_type, "lat": user_lat, "lng": user_lng},
                reasoning=f"No platform providers available for requested slot. Discovered {len(google_providers)} alternative providers on Google Maps.",
                confidence=95,
                output_data={"providers_found": len(google_providers)}
            )

            return {
                "status": "no_available_slot",
                "intent": intent.model_dump(),
                "best_match": best_match.model_dump(),
                "availability": availability,
                "message": "No provider available at the requested time.",
                "alternate_slots": availability.get("alternate_slots", []),
                "google_providers": google_providers,
            }

    # STEP 5: Dynamic Pricing
    demand_level = estimate_demand_level(intent.service_type, target_hour)
    price = calculate_price(
        provider=assigned_provider,
        distance_km=best_match.distance_km,
        urgency=intent.urgency,
        complexity=intent.complexity,
        budget_sensitivity=intent.budget_sensitivity,
        demand_level=demand_level,
        all_candidates=all_scored,
    )

    log_trace(
        stage="orchestration_proposal",
        input_data={"user_message": payload.message},
        reasoning=(
            f"Orchestrated proposal: "
            f"NLU ({intent.confidence_score}% confidence) → "
            f"Matched {assigned_provider['name']} (score: {best_match.match_score}) → "
            f"Scheduled {target_date.strftime('%Y-%m-%d')} {target_hour:02d}:00 → "
            f"Priced Rs.{price.total}."
        ),
        confidence=95,
        output_data={"provider_id": assigned_provider["id"]},
    )

    # Fetch phone for the best match if missing
    phone = assigned_provider.get("phone")
    if not phone and assigned_provider.get("place_id"):
        from matcher import get_place_phone_number
        phone = get_place_phone_number(assigned_provider["place_id"])
    
    final_phone = phone or assigned_provider.get("phone")

    return {
        "status": "proposal_pending",
        "intent": intent.model_dump(),
        "match": best_match.model_dump(),
        "all_matches": [m.model_dump() for m in top_matches],
        "scheduling": {
            "date": target_date.strftime("%Y-%m-%d"),
            "time": f"{target_hour:02d}:00",
            "availability": availability,
        },
        "pricing": price.model_dump(),
        "provider": {
            "id": assigned_provider["id"],
            "name": assigned_provider["name"],
            "rating": assigned_provider.get("rating", 4.0),
            "review_count": assigned_provider.get("review_count", 0),
            "distance_km": best_match.distance_km,
            "phone": final_phone,
            "place_id": assigned_provider.get("place_id", ""),
            "source": assigned_provider.get("source", "platform"),
            "is_open": assigned_provider.get("is_open", True),
            "service": intent.service_type,
            "address": assigned_provider.get("address", "Location from Google Maps"),
            "on_time_pct": assigned_provider.get("on_time_percentage", 90),
        }
    }


# ========================
# BOOKING MANAGEMENT
# ========================

@app.get("/booking/{booking_id}")
async def get_booking_details(booking_id: str):
    booking = get_booking(booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    traces = get_traces_by_booking(booking_id)
    return {"booking": booking, "traces": traces}


@app.get("/bookings/user/{user_id}")
async def get_bookings_for_user(user_id: str):
    return {"bookings": get_user_bookings(user_id)}


@app.post("/booking/{booking_id}/cancel")
async def cancel_booking_endpoint(booking_id: str, payload: CancelPayload):
    booking = cancel_booking(booking_id, payload.cancelled_by)
    if not booking:
        raise HTTPException(404, "Booking not found")

    result = {"status": "cancelled", "booking": booking}

    # Auto-reschedule if provider cancelled
    if payload.cancelled_by == "provider":
        from matcher import _load_providers
        providers = _load_providers()
        reschedule = auto_reschedule(booking_id, providers)
        result["reschedule"] = reschedule
        if reschedule and reschedule.get("booking"):
            result["booking"] = reschedule["booking"]

    return result


@app.post("/booking/{booking_id}/status")
async def update_status(booking_id: str, status: str = Query(...)):
    valid = ["confirmed", "provider_en_route", "in_progress", "completed"]
    if status not in valid:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid}")
    booking = update_booking_status(booking_id, status)
    if not booking:
        raise HTTPException(404, "Booking not found")
    return {"status": "updated", "booking": booking}


# ========================
# FEEDBACK & QUALITY
# ========================

@app.post("/booking/{booking_id}/rate")
async def rate_service(booking_id: str, payload: FeedbackPayload):
    booking = get_booking(booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    result = await process_feedback(
        client=openai_client,
        model=LLM_MODEL,
        booking_id=booking_id,
        provider_id=booking["provider_id"],
        rating=payload.rating,
        review_text=payload.review_text,
    )

    update_booking_status(booking_id, "rated", {"feedback": {
        "rating": payload.rating,
        "review_text": payload.review_text,
        "result": result,
    }})

    return result


@app.get("/provider/{provider_id}/reputation")
async def provider_reputation(provider_id: str):
    return get_provider_reputation(provider_id)


# ========================
# DISPUTES
# ========================

@app.post("/booking/{booking_id}/dispute")
async def open_dispute(booking_id: str, payload: DisputePayload):
    result = await process_dispute(
        client=openai_client,
        model=LLM_MODEL,
        booking_id=booking_id,
        dispute_type=payload.dispute_type,
        description=payload.description,
        evidence_urls=payload.evidence_urls,
    )
    return result


# ========================
# PROVIDER OPTIMIZATION
# ========================

@app.get("/providers/dashboard")
async def providers_dashboard():
    return get_workload_dashboard()


@app.get("/providers/forecast")
async def demand_forecast_endpoint(service_type: Optional[str] = None):
    return get_demand_forecast(service_type)


@app.get("/providers/{provider_id}/optimize")
async def optimize_provider(provider_id: str):
    return get_recommended_slots(provider_id)


@app.get("/providers/earnings")
async def earnings_analysis():
    return get_fair_earning_analysis()


# ========================
# STRESS TESTS
# ========================

@app.get("/simulate/scenarios")
async def list_test_scenarios():
    return {"scenarios": list_scenarios()}


@app.get("/simulate/scenario/{name}")
async def get_test_scenario(name: str):
    return get_scenario(name)


@app.post("/simulate/run/{name}")
async def run_stress_test(name: str):
    """Execute a single stress test scenario against the live system."""
    result = await execute_scenario(name, handle_request, openai_client, LLM_MODEL)
    log_trace(
        stage="stress_test_execution",
        input_data={"scenario": name},
        reasoning=f"Stress test '{name}' completed with status: {result.get('status')}. {result.get('summary', '')}",
        confidence=100,
        output_data={"status": result.get("status"), "summary": result.get("summary")},
    )
    return result


@app.post("/simulate/run-all")
async def run_all_stress_tests():
    """Execute all stress test scenarios sequentially."""
    results = await execute_all_scenarios(handle_request, openai_client, LLM_MODEL)
    log_trace(
        stage="stress_test_suite",
        input_data={"total_scenarios": results.get("total_scenarios")},
        reasoning=f"Full stress test suite: {results.get('passed')}/{results.get('total_scenarios')} passed ({results.get('pass_rate')})",
        confidence=100,
        output_data={"pass_rate": results.get("pass_rate")},
    )
    return results


# ========================
# ANTIGRAVITY TRACES
# ========================

@app.get("/traces")
async def get_traces(limit: int = 50):
    return {"traces": get_recent_traces(limit)}


@app.get("/traces/booking/{booking_id}")
async def get_booking_traces(booking_id: str):
    return {"traces": get_traces_by_booking(booking_id)}


@app.delete("/traces")
async def clear_all_traces():
    clear_traces()
    return {"status": "cleared"}


# ========================
# GOOGLE PLACES — REAL PROVIDER DISCOVERY
# ========================

@app.get("/api/nearby-providers")
async def nearby_providers(
    lat: float = Query(...),
    lng: float = Query(...),
    service: str = Query("electrician"),
    radius: int = Query(5000),
):
    """Discover real providers via Google Places API + merge with platform data."""
    from matcher import enrich_places_with_contact_details, fetch_real_providers_from_google
    real_places = enrich_places_with_contact_details(
        fetch_real_providers_from_google(lat, lng, service, radius),
        limit=10,
    )
    if real_places:
        log_trace(
            stage="google_places_discovery",
            input_data={"lat": lat, "lng": lng, "service": service, "radius": radius},
            reasoning=f"Found {len(real_places)} real providers for '{service}' within {radius}m via Google Places API.",
            confidence=90,
            output_data={"count": len(real_places)},
        )

    # Also include matching platform providers
    from matcher import _load_providers, _haversine
    mock = _load_providers()
    mock_nearby = []
    for p in mock:
        dist = _haversine(lat, lng, p["lat"], p["lng"])
        if dist <= radius / 1000 and p["service"].lower() == service.lower():
            mock_nearby.append({**p, "distance_km": round(dist, 2), "source": "platform"})
    mock_nearby.sort(key=lambda x: x["distance_km"])

    return {
        "user_location": {"lat": lat, "lng": lng},
        "service": service,
        "radius_m": radius,
        "google_places": real_places,
        "platform_providers": mock_nearby,
        "total": len(real_places) + len(mock_nearby),
    }


@app.get("/api/config")
async def get_config():
    """Expose safe config to frontend (Maps key for map rendering)."""
    has_key = bool(GOOGLE_MAPS_KEY and GOOGLE_MAPS_KEY != "your_google_maps_key_here")
    return {"maps_api_key": GOOGLE_MAPS_KEY if has_key else "", "has_maps_key": has_key}


@app.get("/api/geocode")
async def reverse_geocode(lat: float = Query(...), lng: float = Query(...)):
    """Reverse geocode GPS coordinates to a human-readable address."""
    if not GOOGLE_MAPS_KEY or GOOGLE_MAPS_KEY == "your_google_maps_key_here":
        return {"address": f"{lat:.4f}, {lng:.4f}", "components": {}, "source": "fallback"}
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"latlng": f"{lat},{lng}", "key": GOOGLE_MAPS_KEY}
        resp = http_requests.get(url, params=params, timeout=5)
        data = resp.json()
        if data.get("results"):
            result = data["results"][0]
            components = {}
            for comp in result.get("address_components", []):
                for t in comp.get("types", []):
                    components[t] = comp.get("long_name", "")
            return {
                "address": result.get("formatted_address", ""),
                "components": components,
                "source": "google_geocoding",
            }
    except Exception as e:
        logger.warning(f"Geocoding error: {e}")
    return {"address": f"{lat:.4f}, {lng:.4f}", "components": {}, "source": "fallback"}


# ========================
# AUTOMATED WHATSAPP OUTREACH
# ========================

class AutomateProviderPayload(BaseModel):
    lat: float
    lng: float
    service_type: str = "electrician"
    message: str = ""  # optional custom message; default is hardcoded below
    radius: int = 5000
    target_language: str = "english"

@app.post("/api/automate-nearest-provider")
async def automate_nearest_provider(payload: AutomateProviderPayload):
    """
    Full automation: find nearest real provider on Google Maps,
    get their phone number, and send an SMS message.
    """
    from matcher import enrich_places_with_contact_details, fetch_real_providers_from_google, find_platform_providers_nearby
    from sms_service import send_sms_message

    log_trace(
        stage="automate_nearest_start",
        input_data={"lat": payload.lat, "lng": payload.lng, "service": payload.service_type},
        reasoning=f"User requested automated outreach for '{payload.service_type}' near ({payload.lat}, {payload.lng}).",
        confidence=100,
    )

    # Step 1 — discover real providers via Google Places
    places = enrich_places_with_contact_details(
        fetch_real_providers_from_google(payload.lat, payload.lng, payload.service_type, payload.radius),
        limit=5,
    )
    provider_source = "google_places"

    if not places:
        places = find_platform_providers_nearby(payload.lat, payload.lng, payload.service_type, payload.radius)
        provider_source = "platform"

    if not places:
        log_trace(
            stage="automate_nearest_no_results",
            input_data={"service": payload.service_type},
            reasoning="No Google Places or platform providers were found for this service.",
            confidence=100,
        )
        return {
            "status": "no_provider_found",
            "message": f"No '{payload.service_type}' providers found within {payload.radius}m of your location.",
        }

    # Step 2 — pick the nearest one
    nearest = places[0]  # already sorted by distance_km

    log_trace(
        stage="automate_nearest_selected",
        input_data={"name": nearest["name"], "distance_km": nearest["distance_km"]},
        reasoning=f"Nearest provider is '{nearest['name']}' at {nearest['distance_km']} km.",
        confidence=95,
        output_data=nearest,
    )

    # Step 3 — fetch phone number from Google Place Details
    phone = nearest.get("phone")

    if not phone:
        log_trace(
            stage="automate_nearest_no_phone",
            input_data={"name": nearest["name"], "place_id": nearest.get("place_id", "")},
            reasoning="Provider was found, but Google Place Details did not return a public phone number.",
            confidence=80,
        )
        return {
            "status": "no_phone_number",
            "provider": {
                "name": nearest["name"],
                "address": nearest.get("address", ""),
                "distance_km": nearest["distance_km"],
                "rating": nearest.get("rating"),
                "phone": None,
                "source": provider_source,
            },
            "message": "Provider found, but no public phone number is listed on Google Maps.",
        }

    # Step 4 — compose & send SMS message
    body = payload.message.strip() if payload.message.strip() else (
        f"Assalam o Alaikum! I need a {payload.service_type} urgently. "
        f"I found your business '{nearest['name']}' on Google Maps. "
        f"Can you please come to my location? JazakAllah."
    )

    sent, result_msg = await send_sms_message(openai_client, LLM_MODEL, phone, body, payload.target_language)

    log_trace(
        stage="automate_nearest_message_sent",
        input_data={"phone": phone, "message_preview": body[:80]},
        reasoning=f"SMS message {'sent successfully' if sent else 'FAILED'} to {phone} for {nearest['name']}.",
        confidence=95 if sent else 50,
    )

    return {
        "status": "message_sent" if sent else "message_failed",
        "provider": {
            "name": nearest["name"],
            "address": nearest.get("address", ""),
            "distance_km": nearest["distance_km"],
            "rating": nearest.get("rating"),
            "phone": phone,
            "source": provider_source,
        },
        "message_body": result_msg if sent else None,
        "error": result_msg if not sent else None,
        "sms_delivered": sent,
    }

# ========================
# CHAT-BASED PROVIDER DISCOVERY + SMS CONTACT
# ========================

class FindProviderPayload(BaseModel):
    lat: float
    lng: float
    service_type: str = "electrician"
    radius: int = 5000

@app.post("/api/find-provider")
async def find_provider(payload: FindProviderPayload):
    """
    Step 1: Find the nearest real provider for a service and return full details.
    The frontend shows these details and asks if user wants to contact via SMS.
    """
    from matcher import enrich_places_with_contact_details, fetch_real_providers_from_google, find_platform_providers_nearby

    log_trace(
        stage="find_provider_start",
        input_data={"lat": payload.lat, "lng": payload.lng, "service": payload.service_type},
        reasoning=f"Searching for nearest '{payload.service_type}' provider near ({payload.lat}, {payload.lng}).",
        confidence=100,
    )

    places = enrich_places_with_contact_details(
        fetch_real_providers_from_google(payload.lat, payload.lng, payload.service_type, payload.radius),
        limit=5,
    )
    provider_source = "google_places"

    if not places:
        places = find_platform_providers_nearby(payload.lat, payload.lng, payload.service_type, payload.radius)
        provider_source = "platform"

    if not places:
        return {
            "status": "no_provider_found",
            "message": f"No '{payload.service_type}' providers found within {payload.radius}m of your location.",
        }

    nearest = places[0]

    # Use the normalized phone number fetched from Google Place Details.
    place_id = nearest.get("place_id", "")
    phone = nearest.get("phone")

    log_trace(
        stage="find_provider_result",
        input_data={"name": nearest["name"], "distance_km": nearest["distance_km"]},
        reasoning=f"Found nearest provider: '{nearest['name']}' at {nearest['distance_km']}km. Phone: {'found' if phone else 'not found'}.",
        confidence=95,
        output_data={"name": nearest["name"], "phone": phone, "distance_km": nearest["distance_km"]},
    )

    return {
        "status": "provider_found",
        "provider": {
            "name": nearest["name"],
            "address": nearest.get("address", ""),
            "distance_km": nearest["distance_km"],
            "rating": nearest.get("rating"),
            "review_count": nearest.get("review_count", 0),
            "is_open": nearest.get("is_open"),
            "phone": phone,
            "raw_phone": nearest.get("raw_phone"),
            "website": nearest.get("website", ""),
            "google_url": nearest.get("google_url", ""),
            "place_id": place_id,
            "lat": nearest.get("lat"),
            "lng": nearest.get("lng"),
            "service": payload.service_type,
            "source": provider_source,
        },
        "all_providers": [
            {
                "name": p["name"],
                "address": p.get("address", ""),
                "distance_km": p["distance_km"],
                "rating": p.get("rating"),
                "review_count": p.get("review_count", 0),
                "is_open": p.get("is_open"),
                "place_id": p.get("place_id", ""),
                "phone": p.get("phone"),
                "raw_phone": p.get("raw_phone"),
                "website": p.get("website", ""),
                "google_url": p.get("google_url", ""),
                "lat": p.get("lat"),
                "lng": p.get("lng"),
                "service": payload.service_type,
                "source": p.get("source", provider_source),
            }
            for p in places[:5]
        ],
    }


class SendSMSPayload(BaseModel):
    phone: str = ""
    place_id: str = ""
    provider_name: str
    service_type: str = "electrician"
    message: str = ""  # Optional custom message
    target_language: str = "english"
    channel: str = "sms"

@app.post("/api/send-sms")
async def send_sms_to_provider(payload: SendSMSPayload):
    """
    Step 2: After user confirms, send an SMS message to the provider.
    """
    from sms_service import send_sms_message
    from matcher import get_place_phone_number

    channel = payload.channel.lower().strip()
    if channel not in {"sms", "whatsapp"}:
        raise HTTPException(400, "channel must be either 'sms' or 'whatsapp'")

    target_phone = payload.phone
    if not target_phone and payload.place_id:
        target_phone = get_place_phone_number(payload.place_id)

    if not target_phone:
        return {
            "status": "no_phone_number",
            "channel": channel,
            "provider_name": payload.provider_name,
            "phone": None,
            "message_body": None,
            "error": "No public phone number is listed for this provider.",
            "sms_delivered": False,
        }

    body = payload.message.strip() if payload.message.strip() else (
        f"Assalam o Alaikum! I need a {payload.service_type} urgently. "
        f"I found your business '{payload.provider_name}' on Google Maps. "
        f"Can you please come to my location? JazakAllah."
    )

    sent, result_msg = await send_sms_message(
        openai_client,
        LLM_MODEL,
        target_phone,
        body,
        payload.target_language,
        channel=channel,
    )

    log_trace(
        stage=f"{channel}_sent",
        input_data={"phone": target_phone, "provider": payload.provider_name, "channel": channel},
        reasoning=f"{channel.upper()} message {'sent successfully' if sent else 'FAILED'} to {target_phone} for {payload.provider_name}.",
        confidence=95 if sent else 50,
    )

    return {
        "status": "message_sent" if sent else "message_failed",
        "channel": channel,
        "provider_name": payload.provider_name,
        "phone": target_phone,
        "message_body": result_msg if sent else None,
        "error": result_msg if not sent else None,
        "sms_delivered": sent,
    }


@app.get("/api/sms-logs")
async def get_sms_logs_endpoint():
    """
    Get all captured SMS/WhatsApp logs.
    """
    from sms_service import get_sms_logs
    return get_sms_logs()


class BookProviderPayload(BaseModel):
    user_id: str
    provider: dict
    service_type: str
    user_lat: float = 0.0
    user_lng: float = 0.0

@app.post("/api/book-provider")
async def book_provider(payload: BookProviderPayload):
    """
    Directly book a provider on the platform.
    """
    from pricing import calculate_price, estimate_demand_level
    from booking_engine import create_booking

    provider = payload.provider
    # Ensure provider has standard fields
    if "id" not in provider:
        provider["id"] = provider.get("place_id") or f"gp_{provider['name'].lower().replace(' ', '_')[:10]}"
    if "on_time_percentage" not in provider:
        provider["on_time_percentage"] = provider.get("on_time_pct") or 90
    if "cancellation_rate" not in provider:
        provider["cancellation_rate"] = 2
    if "rating" not in provider:
        provider["rating"] = 4.0

    target_date = datetime.now(timezone.utc) + timedelta(days=1)
    target_hour = 10

    # Pricing
    demand_level = estimate_demand_level(payload.service_type, target_hour)
    price = calculate_price(
        provider=provider,
        distance_km=provider.get("distance_km", 2.0),
        urgency="medium",
        complexity="basic",
        budget_sensitivity="medium",
        demand_level=demand_level,
        all_candidates=[]
    )

    booking = create_booking(
        user_id=payload.user_id,
        provider=provider,
        service_type=payload.service_type,
        scheduled_date=target_date.strftime("%Y-%m-%d"),
        scheduled_hour=target_hour,
        price_total=price.total,
        price_breakdown=price.model_dump(),
        location="G-13, Islamabad",
        user_lat=payload.user_lat,
        user_lng=payload.user_lng,
    )

    return {
        "status": "booking_confirmed",
        "booking_id": booking.booking_id,
        "intent": {
            "service_type": payload.service_type,
            "complexity": "basic",
            "confidence_score": 100.0,
            "original_language": "english",
        },
        "match": {
            "provider_id": provider["id"],
            "provider_name": provider["name"],
            "rating": provider.get("rating", 4.0),
            "on_time_pct": provider.get("on_time_percentage", 90),
            "distance_km": provider.get("distance_km", 2.0),
            "match_score": 100.0,
            "reasoning": f"Directly booked by user.",
        },
        "pricing": price.model_dump(),
        "scheduling": {
            "date": target_date.strftime("%Y-%m-%d"),
            "time": f"{target_hour:02d}:00",
        },
        "booking": booking.model_dump(),
        "notifications": booking.notifications,
    }



# ========================
# ALERT SYSTEM
# ========================

@app.get("/api/alerts")
async def get_alerts(user_id: str = Query("mobile_user_1")):
    """Get active alerts for a user."""
    # Generate dynamic alerts from system state
    alerts = list(_alerts)

    # Check for provider cancellations
    bookings = get_user_bookings(user_id)
    for b in bookings:
        if b.get("status") == "cancelled" and b.get("cancelled_by") == "provider":
            alerts.append({
                "id": f"alert_cancel_{b['booking_id']}",
                "type": "warning",
                "title": "Provider Cancelled",
                "message": f"{b.get('provider_name', 'Provider')} cancelled your booking. We're finding a replacement.",
                "booking_id": b["booking_id"],
                "timestamp": b.get("updated_at", ""),
                "action": "reschedule",
            })
        if b.get("status") == "provider_en_route":
            alerts.append({
                "id": f"alert_enroute_{b['booking_id']}",
                "type": "info",
                "title": "Provider On The Way",
                "message": f"{b.get('provider_name', 'Provider')} is heading to your location now.",
                "booking_id": b["booking_id"],
                "timestamp": b.get("updated_at", ""),
                "action": "track",
            })
        if b.get("status") == "completed" and not b.get("feedback"):
            alerts.append({
                "id": f"alert_rate_{b['booking_id']}",
                "type": "success",
                "title": "Rate Your Service",
                "message": f"How was {b.get('provider_name', 'the provider')}? Tap to leave a review.",
                "booking_id": b["booking_id"],
                "timestamp": b.get("updated_at", ""),
                "action": "rate",
            })
        if b.get("dispute") and b["dispute"].get("status") == "resolved":
            alerts.append({
                "id": f"alert_dispute_{b['booking_id']}",
                "type": "success",
                "title": "Dispute Resolved",
                "message": f"Your dispute for booking {b['booking_id']} has been resolved. Refund: Rs. {b['dispute'].get('refund_amount', 0)}",
                "booking_id": b["booking_id"],
                "timestamp": b.get("updated_at", ""),
                "action": "view",
            })

    return {"alerts": alerts}


@app.post("/api/alerts")
async def create_alert(title: str = Query(...), message: str = Query(...), alert_type: str = Query("info")):
    """Push a custom alert."""
    from datetime import datetime, timezone
    alert = {
        "id": f"alert_{len(_alerts)+1}",
        "type": alert_type,
        "title": title,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _alerts.append(alert)
    return alert


# ========================
# HEALTH CHECK
# ========================

@app.get("/")
async def health():
    return {
        "service": "Service Orchestrator — Antigravity Edition",
        "version": "2.0.0",
        "status": "operational",
        "modules": ["nlu", "matcher", "scheduler", "pricing", "booking", "quality", "disputes", "optimizer"],
        "llm": LLM_MODEL,
    }




# Serve mobile web app
@app.get("/app")
async def serve_mobile_app():
    return RedirectResponse(url="/mobile/index.html")

app.mount("/mobile", StaticFiles(directory="mobile"), name="mobile")


if __name__ == "__main__":
    uvicorn.run("orchestrator:app", host="0.0.0.0", port=8000, reload=True)
