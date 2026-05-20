"""
Advanced Provider Matcher — 10-factor weighted scoring with Antigravity traces.
Factors: distance, availability, rating, review recency, reliability,
skill specialization, price competitiveness, cancellation risk,
risk score, and user preference.
"""
import json
import math
import logging
import re
import requests
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from trace_logger import log_trace

logger = logging.getLogger("orchestrator.matcher")

MAPS_API_KEY = ""  # Set from .env via orchestrator
BASE_DIR = Path(__file__).resolve().parent
PROVIDERS_FILE = BASE_DIR / "data" / "providers.json"
_PLACE_DETAILS_CACHE: dict[str, dict] = {}

# Scoring weights — 10 factors (must sum to 100)
WEIGHTS = {
    "distance": 12,
    "availability": 12,
    "rating": 13,
    "review_recency": 5,
    "reliability": 13,
    "skill_match": 12,
    "price": 8,
    "cancellation_risk": 8,
    "risk_score": 9,
    "user_preference": 8,
}


class MatchResult(BaseModel):
    provider_id: str
    provider_name: str
    match_score: float
    reasoning: str
    estimated_price: int = 0
    distance_km: float = 0
    travel_time_mins: int = 0
    skill_level: str = ""
    rating: float = 0
    on_time_pct: int = 0
    cancellation_rate: int = 0
    availability_status: str = ""


def _load_providers():
    try:
        with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load provider data: {e}")
        return []



def _has_maps_key() -> bool:
    return bool(MAPS_API_KEY and MAPS_API_KEY != "your_google_maps_key_here")


def _haversine(lat1, lng1, lat2, lng2):
    """Calculate distance in km between two GPS points."""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def normalize_phone_number(phone: str | None, default_country_code: str = "+92") -> Optional[str]:
    """Normalize scraped phone numbers into a stable display/send format."""
    if not phone:
        return None

    raw = str(phone).strip()
    if not raw:
        return None

    if raw.lower().startswith("whatsapp:"):
        prefix, number = raw.split(":", 1)
        normalized = normalize_phone_number(number, default_country_code)
        return f"{prefix}:{normalized}" if normalized else None

    number = re.sub(r"[^\d+]", "", raw)
    if not number:
        return None

    # Keep already international numbers stable.
    if number.startswith("+"):
        international_digits = re.sub(r"\D", "", number)
        return f"+{international_digits}" if international_digits else None

    digits = re.sub(r"\D", "", number)
    if not digits:
        return None

    # Pakistan local mobile/landline formats commonly come back as 03..., 051..., or 92...
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if digits.startswith("92"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"{default_country_code}{digits[1:]}"
    if len(digits) == 10 and digits.startswith("3"):
        return f"{default_country_code}{digits}"

    return f"{default_country_code}{digits}" if default_country_code == "+92" else f"+{digits}"


def fetch_real_providers_from_google(lat: float, lng: float, service: str, radius: int = 5000):
    """Discover real providers via Google Places API."""
    SERVICE_KEYWORDS = {
        "ac repair": "AC repair HVAC air conditioning service",
        "electrician": "electrician electrical services electrical contractor",
        "plumber": "plumber plumbing services pipe repair",
        "beautician": "beauty salon beautician spa parlour",
        "mechanic": "auto repair car mechanic workshop garage",
        "tutor": "tutor coaching center academy private teacher",
        "carpenter": "carpenter woodwork furniture repair",
        "painter": "painter house painting wall painter",
        "cleaning": "cleaning service maid house cleaning",
        "pest control": "pest control fumigation exterminator",
        "locksmith": "locksmith key maker lock repair",
        "appliance repair": "appliance repair washing machine refrigerator",
    }
    keyword = SERVICE_KEYWORDS.get(service.lower(), service)
    real_places = []

    if _has_maps_key():
        try:
            # Try Nearby Search first
            url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            params = {
                "location": f"{lat},{lng}",
                "radius": radius,
                "keyword": keyword,
                "key": MAPS_API_KEY,
            }
            resp = requests.get(url, params=params, timeout=8)
            data = resp.json()
            results = data.get("results", [])

            # Fallback to Text Search if Nearby Search returns few results
            if len(results) < 3:
                text_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
                text_params = {
                    "query": f"{keyword} near me",
                    "location": f"{lat},{lng}",
                    "radius": radius,
                    "key": MAPS_API_KEY,
                }
                text_resp = requests.get(text_url, params=text_params, timeout=8)
                text_data = text_resp.json()
                existing_ids = {r.get("place_id") for r in results}
                for r in text_data.get("results", []):
                    if r.get("place_id") not in existing_ids:
                        results.append(r)

            for place in results[:15]:
                loc = place.get("geometry", {}).get("location", {})
                p_lat = loc.get("lat", 0)
                p_lng = loc.get("lng", 0)
                dist = round(_haversine(lat, lng, p_lat, p_lng), 2) if p_lat else 99
                real_places.append({
                    "id": f"gp_{place.get('place_id', '')[:12]}",
                    "place_id": place.get("place_id", ""),
                    "name": place.get("name", "Unknown"),
                    "service": service.lower(),
                    "address": place.get("vicinity", place.get("formatted_address", "")),
                    "rating": place.get("rating", 4.0), # Default good rating if none
                    "review_count": place.get("user_ratings_total", 0),
                    "lat": p_lat,
                    "lng": p_lng,
                    "distance_km": dist,
                    "is_open": place.get("opening_hours", {}).get("open_now", None),
                    "source": "google_places",
                    "base_rate": 1500, # Mock base rate
                    "on_time_percentage": 90, # Assume generally reliable
                    "cancellation_rate": 2, # Assume low cancellation
                    "skill_level": "intermediate",
                    "capacity_per_day": 8,
                    "current_load": 2,
                    "review_recency_days": 10,
                    "recent_negative_reviews": 0,
                    "availability": {
                        "monday": ["08:00-18:00"],
                        "tuesday": ["08:00-18:00"],
                        "wednesday": ["08:00-18:00"],
                        "thursday": ["08:00-18:00"],
                        "friday": ["08:00-18:00"],
                        "saturday": ["09:00-16:00"],
                        "sunday": ["10:00-14:00"]
                    }
                })
            real_places.sort(key=lambda x: x["distance_km"])
        except Exception as e:
            logger.warning(f"Google Places API fallback error: {e}")
            
    return real_places


def find_platform_providers_nearby(lat: float, lng: float, service: str, radius: int = 5000, limit: int = 5) -> list[dict]:
    """Return nearest local platform providers when live Google data is unavailable."""
    service_lower = service.lower()
    radius_km = radius / 1000
    providers = [
        p for p in _load_providers()
        if p.get("service", "").lower() == service_lower
    ]

    enriched = []
    for provider in providers:
        dist = round(_haversine(lat, lng, provider["lat"], provider["lng"]), 2)
        enriched.append({
            **provider,
            "distance_km": dist,
            "source": "platform",
            "address": provider.get("address", f"{provider.get('service', 'Service').title()} provider"),
            "phone": normalize_phone_number(provider.get("phone")),
            "is_open": None,
        })

    candidates = [p for p in enriched if p["distance_km"] <= radius_km] or enriched
    candidates.sort(key=lambda p: p["distance_km"])
    return candidates[:limit]


def get_place_phone_number(place_id: str) -> Optional[str]:
    """Fetch phone number for a Google Places result using Place Details API."""
    if not _has_maps_key():
        logger.warning("No Maps API key — cannot fetch phone number.")
        return None
    try:
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            "place_id": place_id,
            "fields": "international_phone_number,formatted_phone_number,name",
            "key": MAPS_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=8)
        data = resp.json()
        result = data.get("result", {})
        phone = result.get("international_phone_number") or result.get("formatted_phone_number")
        if phone:
            logger.info(f"📞 Got phone for {result.get('name', place_id)}: {phone}")
        else:
            logger.warning(f"No phone number found for place_id={place_id}")
        return phone
    except Exception as e:
        logger.error(f"Place Details API error: {e}")
        return None


def get_place_contact_details(place_id: str) -> dict:
    """Fetch and cache reliable contact details for a Google Places result."""
    if not place_id:
        return {}
    if place_id in _PLACE_DETAILS_CACHE:
        return _PLACE_DETAILS_CACHE[place_id]

    details = {}

    if _has_maps_key():
        try:
            url = "https://maps.googleapis.com/maps/api/place/details/json"
            params = {
                "place_id": place_id,
                "fields": "name,international_phone_number,formatted_phone_number,formatted_address,website,url",
                "key": MAPS_API_KEY,
            }
            resp = requests.get(url, params=params, timeout=8)
            data = resp.json()
            status = data.get("status", "")
            if status and status != "OK":
                logger.warning(f"Place Details returned {status} for place_id={place_id}: {data.get('error_message', '')}")
            else:
                result = data.get("result", {})
                raw_phone = result.get("international_phone_number") or result.get("formatted_phone_number")
                phone = normalize_phone_number(raw_phone)
                details = {
                    "name": result.get("name", ""),
                    "phone": phone,
                    "raw_phone": raw_phone,
                    "formatted_address": result.get("formatted_address", ""),
                    "website": result.get("website", ""),
                    "google_url": result.get("url", ""),
                }
        except Exception as e:
            logger.error(f"Place Details API error: {e}")

    # Fallback mock phone number if no phone number was returned/scraped
    if not details.get("phone"):
        name = details.get("name", f"Provider {place_id[:6]}")
        name_hash = sum(ord(c) for c in name) % 9000000 + 1000000
        details["phone"] = f"+92300{name_hash}"
        details["raw_phone"] = f"0300-{str(name_hash)[:3]}-{str(name_hash)[3:]} (Demo)"
        if "name" not in details:
            details["name"] = name

    _PLACE_DETAILS_CACHE[place_id] = details
    return details


def get_place_phone_number(place_id: str) -> Optional[str]:
    """Fetch normalized phone number for a Google Places result."""
    details = get_place_contact_details(place_id)
    return details.get("phone") if details else None


def enrich_places_with_contact_details(places: list[dict], limit: int | None = None) -> list[dict]:
    """Attach normalized phone numbers and contact metadata to Google Places results."""
    enriched = []
    max_items = len(places) if limit is None else min(limit, len(places))

    for index, place in enumerate(places):
        item = dict(place)
        if index < max_items and item.get("place_id"):
            details = get_place_contact_details(item["place_id"])
            if details:
                item["phone"] = details.get("phone") or item.get("phone")
                item["raw_phone"] = details.get("raw_phone") or item.get("raw_phone")
                item["website"] = details.get("website") or item.get("website")
                item["google_url"] = details.get("google_url") or item.get("google_url")
                if details.get("formatted_address"):
                    item["address"] = details["formatted_address"]
        
        # Fallback mock if still missing
        if not item.get("phone"):
            name_hash = sum(ord(c) for c in item["name"]) % 9000000 + 1000000
            item["phone"] = f"+92300{name_hash}"
            item["raw_phone"] = f"0300-{str(name_hash)[:3]}-{str(name_hash)[3:]} (Demo)"

        enriched.append(item)

    return enriched


def get_road_data(origin_lat, origin_lng, dest_lat, dest_lng):
    """Get real road distance/time via Google Routes API with Haversine fallback."""
    if not _has_maps_key():
        dist = round(_haversine(origin_lat, origin_lng, dest_lat, dest_lng), 1)
        return dist, max(5, int(dist * 3))

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": MAPS_API_KEY, "X-Goog-FieldMask": "routes.distanceMeters,routes.duration"}
    body = {"origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}}, "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lng}}}, "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE"}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=5)
        data = resp.json()
        dist_km = round(data['routes'][0]['distanceMeters'] / 1000, 1)
        dur_mins = int(data['routes'][0]['duration'][:-1]) // 60
        return dist_km, dur_mins
    except Exception as e:
        logger.warning(f"Maps API fallback: {e}")
        dist = round(_haversine(origin_lat, origin_lng, dest_lat, dest_lng), 1)
        return dist, max(5, int(dist * 3))


def find_best_matches(intent_data, user_lat, user_lng, top_n=3):
    """
    Find and rank top N providers using 10-factor weighted scoring.
    Merges platform mock providers with Google Places real providers.
    Applies proximity boost for urgent requests.
    Returns (list[MatchResult], list[scored_dicts]) sorted by score.
    """
    target_service = intent_data.service_type
    urgency = intent_data.urgency
    complexity = intent_data.complexity
    budget_sensitivity = intent_data.budget_sensitivity
    user_preferences = getattr(intent_data, "user_preferences", []) or []
    user_language = getattr(intent_data, "original_language", "english") or "english"

    # --- MERGE both provider sources ---
    # 1. Platform / mock providers (rich curated data)
    mock_providers = _load_providers()
    mock_candidates = [
        p for p in mock_providers
        if p["service"].lower() == target_service.lower()
    ]

    # 2. Google Places real providers (live API data)
    google_candidates = fetch_real_providers_from_google(user_lat, user_lng, target_service)

    # Merge & deduplicate (prefer mock if names collide)
    seen_names = set()
    candidates = []
    for p in mock_candidates:
        key = p["name"].lower().strip()
        if key not in seen_names:
            seen_names.add(key)
            p["source"] = p.get("source", "platform")
            candidates.append(p)
    for p in google_candidates:
        key = p["name"].lower().strip()
        if key not in seen_names:
            seen_names.add(key)
            candidates.append(p)

    log_trace(
        stage="provider_discovery",
        input_data={"service": target_service, "location": f"{user_lat},{user_lng}"},
        reasoning=(
            f"Merged provider sources: {len(mock_candidates)} platform + "
            f"{len(google_candidates)} Google Places = {len(candidates)} unique candidates "
            f"for '{target_service}'."
        ),
        confidence=95,
        output_data={"platform": len(mock_candidates), "google": len(google_candidates), "merged": len(candidates)},
    )

    if not candidates:
        log_trace(
            stage="provider_matching",
            input_data={"service": target_service, "location": f"{user_lat},{user_lng}"},
            reasoning=f"No providers found for service '{target_service}'.",
            confidence=100,
            output_data=None,
        )
        return []

    # Proximity boost: increase distance weight for urgent requests
    weights = dict(WEIGHTS)
    if urgency in ("high", "emergency"):
        extra = 12
        weights["distance"] += extra
        weights["review_recency"] = max(0, weights["review_recency"] - 2)
        weights["price"] = max(0, weights["price"] - 3)
        weights["cancellation_risk"] = max(0, weights["cancellation_risk"] - 2)
        weights["skill_match"] = max(0, weights["skill_match"] - 2)
        weights["user_preference"] = max(0, weights["user_preference"] - 3)

    # "Best" requested: heavily boost rating and reviews
    if budget_sensitivity == "low":
        weights["rating"] += 15
        weights["price"] = max(0, weights["price"] - 5)
        weights["distance"] = max(0, weights["distance"] - 10)

    scored = []
    for p in candidates:
        dist_km, travel_mins = get_road_data(user_lat, user_lng, p["lat"], p["lng"])

        # 1. Distance score (0-100, closer is better)
        dist_score = max(0, 100 - (dist_km * 5))

        # 2. Availability score
        load = p.get("current_load", 0)
        cap = p.get("capacity_per_day", 4)
        avail_score = max(0, ((cap - load) / cap) * 100) if cap > 0 else 0

        # 3. Rating score (incorporating review count)
        rating = p.get("rating", 3)
        review_count = p.get("review_count", 0)
        rating_score = (rating / 5) * 100
        
        if review_count < 5:
            rating_score *= 0.6  # Heavy penalty for very few reviews
        elif review_count < 20:
            rating_score *= 0.8
            
        if review_count > 100:
            rating_score += 10  # Bonus for high popularity
        if review_count > 500:
            rating_score += 10
            
        rating_score = min(100, rating_score)

        # 4. Review recency (penalize stale/negative)
        recency_days = p.get("review_recency_days", 30)
        neg_reviews = p.get("recent_negative_reviews", 0)
        recency_score = max(0, 100 - recency_days * 2 - neg_reviews * 15)

        # 5. Reliability
        reliability_score = p.get("on_time_percentage", 50)

        # 6. Skill match
        skill_map = {"basic": 40, "intermediate": 70, "expert": 100}
        provider_skill = skill_map.get(p.get("skill_level", "basic"), 40)
        complexity_map = {"basic": 40, "intermediate": 70, "complex": 100}
        needed_skill = complexity_map.get(complexity, 40)
        skill_score = 100 if provider_skill >= needed_skill else max(0, provider_skill - needed_skill + 60)

        # 7. Price competitiveness
        base_rate = p.get("base_rate", 1000)
        max_rate = max(c.get("base_rate", 1000) for c in candidates)
        min_rate = min(c.get("base_rate", 1000) for c in candidates)
        if max_rate > min_rate:
            price_score = ((max_rate - base_rate) / (max_rate - min_rate)) * 100
        else:
            price_score = 50
        if budget_sensitivity == "low":
            price_score = 50  # Don't penalize expensive if budget isn't a concern

        # 8. Cancellation risk
        cancel_rate = p.get("cancellation_rate", 0)
        cancel_score = max(0, 100 - cancel_rate * 5)

        # 9. Risk score (lower risk = better)
        risk = p.get("risk_score", 10)
        risk_score_val = max(0, 100 - risk * 2)

        # 10. User preference match
        pref_score = 50  # default neutral
        # Language match bonus
        prov_langs = [l.lower() for l in p.get("languages", [])]
        if user_language.lower() in ("urdu", "roman urdu", "roman_urdu"):
            if "urdu" in prov_langs:
                pref_score += 20
        elif user_language.lower() == "english":
            if "english" in prov_langs:
                pref_score += 15
        # Certification bonus for complex jobs
        if complexity == "complex" and p.get("certifications"):
            pref_score += 20
        # Gender preference
        for pref in user_preferences:
            if "female" in pref.lower() and p.get("gender") == "female":
                pref_score += 15
            elif "male" in pref.lower() and p.get("gender") == "male":
                pref_score += 10
        # Specialization match
        specializations = [s.lower() for s in p.get("specializations", [])]
        constraints = getattr(intent_data, "constraints", []) or []
        for c in constraints:
            if any(c.lower() in s for s in specializations):
                pref_score += 15
        pref_score = min(100, pref_score)

        # Weighted total (uses adjusted weights for urgency)
        total = (
            dist_score * weights["distance"] / 100 +
            avail_score * weights["availability"] / 100 +
            rating_score * weights["rating"] / 100 +
            recency_score * weights["review_recency"] / 100 +
            reliability_score * weights["reliability"] / 100 +
            skill_score * weights["skill_match"] / 100 +
            price_score * weights["price"] / 100 +
            cancel_score * weights["cancellation_risk"] / 100 +
            risk_score_val * weights["risk_score"] / 100 +
            pref_score * weights["user_preference"] / 100
        )

        detail = (
            f"Dist:{dist_score:.0f}×{weights['distance']}% + "
            f"Avail:{avail_score:.0f}×{weights['availability']}% + "
            f"Rating:{rating_score:.0f}×{weights['rating']}% + "
            f"Recency:{recency_score:.0f}×{weights['review_recency']}% + "
            f"Reliable:{reliability_score:.0f}×{weights['reliability']}% + "
            f"Skill:{skill_score:.0f}×{weights['skill_match']}% + "
            f"Price:{price_score:.0f}×{weights['price']}% + "
            f"Cancel:{cancel_score:.0f}×{weights['cancellation_risk']}% + "
            f"Risk:{risk_score_val:.0f}×{weights['risk_score']}% + "
            f"Pref:{pref_score:.0f}×{weights['user_preference']}%"
        )

        log_trace(
            stage="provider_scoring",
            input_data={"provider": p["name"], "service": target_service},
            reasoning=f"Scored {p['name']}: {total:.1f}/100 [{detail}]",
            confidence=90,
            output_data={"score": round(total, 1), "distance_km": dist_km, "source": p.get("source", "google_places")},
            metadata={"provider_id": p["id"]},
        )

        scored.append({
            "provider": p,
            "score": round(total, 1),
            "dist": dist_km,
            "time": travel_mins,
            "factors": {
                "distance": dist_score, "availability": avail_score, "rating": rating_score,
                "recency": recency_score, "reliability": reliability_score, "skill": skill_score,
                "price": price_score, "cancellation": cancel_score,
                "risk": risk_score_val, "preference": pref_score,
            },
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_n]

    # Log final ranking decision
    if len(top) >= 2:
        winner = top[0]
        runner = top[1]
        log_trace(
            stage="provider_ranking_decision",
            input_data={"service": target_service, "candidates_count": len(candidates)},
            reasoning=(
                f"Selected {winner['provider']['name']} (score: {winner['score']}) over "
                f"{runner['provider']['name']} (score: {runner['score']}). "
                f"Winner has {winner['provider'].get('on_time_percentage', 0)}% reliability, "
                f"{winner['provider'].get('rating', 0)} rating, risk score {winner['provider'].get('risk_score', 'N/A')}, "
                f"and is {winner['dist']}km away. Source: {winner['provider'].get('source', 'platform')}."
            ),
            confidence=92,
            output_data=[{"name": s["provider"]["name"], "score": s["score"]} for s in top],
            alternatives=[{"name": s["provider"]["name"], "score": s["score"], "factors": s["factors"]} for s in scored[1:]],
        )

    results = []
    for s in top:
        p = s["provider"]
        results.append(MatchResult(
            provider_id=p["id"],
            provider_name=p["name"],
            match_score=s["score"],
            reasoning=f"Score {s['score']}/100: {p.get('on_time_percentage', 0)}% reliable, {p.get('rating', 0)}★, {s['dist']}km away, {p.get('skill_level', 'N/A')} skill, risk {p.get('risk_score', 'N/A')}",
            distance_km=s["dist"],
            travel_time_mins=s["time"],
            skill_level=p.get("skill_level", ""),
            rating=p.get("rating", 0),
            on_time_pct=p.get("on_time_percentage", 0),
            cancellation_rate=p.get("cancellation_rate", 0),
            availability_status="available" if s["factors"]["availability"] > 50 else "limited",
        ))

    return results, scored
