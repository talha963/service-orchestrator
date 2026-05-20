"""
Multilingual NLU Engine — Powered by Antigravity (Groq LLM).
Handles Urdu, Roman Urdu, English, mixed/code-switched input,
misspellings, and slang. Extracts structured intent with confidence scoring.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from trace_logger import log_trace

logger = logging.getLogger("orchestrator.nlu")

BASE_DIR = Path(__file__).resolve().parent
LOCATIONS_FILE = BASE_DIR / "data" / "locations.json"

# Location coordinates for common Islamabad areas
LOCATION_COORDS: dict = {}


def _load_locations():
    global LOCATION_COORDS
    try:
        with open(LOCATIONS_FILE, "r", encoding="utf-8") as f:
            LOCATION_COORDS = json.load(f)
    except Exception:
        LOCATION_COORDS = {}


_load_locations()


class ExtractedIntent(BaseModel):
    service_type: str = Field(description="Lowercase service category")
    location: str = Field(default="unspecified", description="Area/sector mentioned")
    urgency: str = Field(default="medium", description="low/medium/high/emergency")
    preferred_time: str = Field(default="flexible", description="When service is needed")
    preferred_date: str = Field(default="today", description="Date for service")
    budget_sensitivity: str = Field(default="medium", description="high/medium/low")
    complexity: str = Field(default="basic", description="basic/intermediate/complex")
    constraints: list[str] = Field(default_factory=list, description="Special requirements")
    user_preferences: list[str] = Field(default_factory=list, description="User preferences")
    confidence_score: float = Field(default=50.0, description="0-100 confidence")
    clarification_questions: list[str] = Field(default_factory=list, description="Questions if low confidence")
    original_language: str = Field(default="english", description="Detected input language")
    sentiment: str = Field(default="neutral", description="frustrated/neutral/urgent/calm")


SERVICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ac repair": ("ac", "a/c", "air conditioner", "air conditioning", "cooling", "hvac", "inverter", "compressor"),
    "electrician": ("electric", "electrician", "bijli", "wiring", "light", "switch", "ups", "generator", "solar", "power", "flicker", "circuit", "breaker"),
    "plumber": ("plumber", "plumbing", "pipe", "leak", "water", "pani", "nalk", "bathroom", "toilet", "drain", "faucet", "tap", "heater"),
    "beautician": ("beauty", "beautician", "makeup", "facial", "hair", "mehndi", "bridal", "spa", "salon", "grooming"),
    "mechanic": ("mechanic", "machenic", "machanic", "mecanic", "car", "bike", "gaari", "engine", "tire", "tyre", "battery", "oil", "brake", "vehicle"),
    "tutor": ("tutor", "teacher", "tuition", "academy", "acdemy", "math", "maths", "science", "physics", "chemistry", "homework", "study", "padhai"),
    "carpenter": ("carpenter", "wood", "furniture", "cabinet", "shelf", "door", "woodwork"),
    "painter": ("painter", "paint", "painting", "whitewash", "wall color", "wall colour"),
    "cleaning": ("cleaning", "cleaner", "maid", "safai", "deep clean", "house clean", "office clean"),
    "pest control": ("pest", "cockroach", "termite", "rat", "fumigation", "insect", "exterminator"),
    "locksmith": ("locksmith", "locked", "key", "lock", "door lock", "safe"),
    "appliance repair": ("appliance", "washing machine", "fridge", "refrigerator", "microwave", "oven"),
}


def _client_has_api_key(client: AsyncOpenAI) -> bool:
    key = str(getattr(client, "api_key", "") or "").strip()
    return bool(key and key not in {"missing", "your_groq_api_key_here"})


def _detect_location(text: str) -> str:
    compact = re.sub(r"[\s\-_]", "", text)
    for name in LOCATION_COORDS:
        lower = name.lower()
        variants = {lower, re.sub(r"[\s\-_]", "", lower)}
        if any(v and (v in text or v in compact) for v in variants):
            return name
    return "unspecified"


def _detect_service(text: str) -> tuple[str, list[str]]:
    matches: list[tuple[str, int, list[str]]] = []
    for service, keywords in SERVICE_KEYWORDS.items():
        hits = []
        for keyword in keywords:
            # Use word boundaries to prevent substring matches (e.g. "ac" in "machenic")
            # For keywords with special chars (like "a/c"), fallback to exact string check
            if re.search(r'\b' + re.escape(keyword) + r'\b', text):
                hits.append(keyword)
            elif keyword in text and not keyword.isalpha():
                hits.append(keyword)
        if hits:
            matches.append((service, len(hits), hits))

    if not matches:
        return "unknown", []

    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[0][0], matches[0][2]


def _heuristic_extract_intent(user_message: str) -> ExtractedIntent:
    text = user_message.lower()
    service_type, matched_keywords = _detect_service(text)
    detected_location = _detect_location(text)

    urgency = "medium"
    if any(w in text for w in ("emergency", "right now", "foran", "abhi", "asap", "urgent", "jaldi")):
        urgency = "emergency" if any(w in text for w in ("emergency", "right now", "abhi")) else "high"
    elif any(w in text for w in ("no rush", "whenever", "flexible", "koi jaldi nahi")):
        urgency = "low"

    preferred_date = "today"
    if any(w in text for w in ("tomorrow", "tmrw", "kal")):
        preferred_date = "tomorrow"
    elif any(w in text for w in ("day after tomorrow", "parson")):
        preferred_date = "day after tomorrow"

    preferred_time = "flexible"
    if any(w in text for w in ("morning", "subah", "subh")):
        preferred_time = "morning"
    elif any(w in text for w in ("afternoon", "dopahar", "dopehar")):
        preferred_time = "afternoon"
    elif any(w in text for w in ("evening", "shaam", "sham")):
        preferred_time = "evening"
    elif any(w in text for w in ("night", "raat")):
        preferred_time = "night"
    elif any(w in text for w in ("asap", "foran", "abhi", "now", "jaldi")):
        preferred_time = "asap"

    explicit_time = re.search(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", text)
    if explicit_time:
        preferred_time = f"{explicit_time.group(1)} {explicit_time.group(2)}"

    budget_sensitivity = "medium"
    if any(w in text for w in ("cheap", "budget", "kam rate", "sasta", "zyada nahi", "low price", "affordable")):
        budget_sensitivity = "high"
    elif any(w in text for w in ("best quality", "money no issue", "paise ki fikr nahi", "premium", "best")):
        budget_sensitivity = "low"

    complexity = "basic"
    if any(w in text for w in ("complete", "full", "overhaul", "rewiring", "compressor", "renovation", "central ac")):
        complexity = "complex"
    elif any(w in text for w in ("repair", "install", "installation", "replace", "leak", "badly", "not cooling", "flicker")):
        complexity = "intermediate"

    original_language = "english"
    if any(w in text for w in ("mujhe", "chahiye", "masla", "hai", "kal", "subah", "pani", "bijli")):
        original_language = "roman_urdu"

    sentiment = "neutral"
    if urgency in ("high", "emergency"):
        sentiment = "urgent"
    if any(w in text for w in ("not working", "kaam nahi", "badly", "terrible", "problem", "masla")):
        sentiment = "frustrated" if urgency != "emergency" else "urgent"

    confidence = 35.0 if service_type == "unknown" else 78.0
    if matched_keywords:
        confidence += min(12, len(matched_keywords) * 4)
    if detected_location != "unspecified":
        confidence += 5
    confidence = min(confidence, 95.0)

    questions = []
    if service_type == "unknown":
        questions = [
            "What service do you need: AC repair, electrician, plumber, mechanic, tutor, or another service?",
            "Please describe the main problem you want fixed.",
        ]

    return ExtractedIntent(
        service_type=service_type,
        location=detected_location,
        urgency=urgency,
        preferred_time=preferred_time,
        preferred_date=preferred_date,
        budget_sensitivity=budget_sensitivity,
        complexity=complexity,
        constraints=matched_keywords[:3],
        confidence_score=confidence,
        clarification_questions=questions,
        original_language=original_language,
        sentiment=sentiment,
    )


SYSTEM_PROMPT = """\
You are the Antigravity NLU Engine — an expert intent-extraction system for an on-demand service marketplace.

Your job is to analyze user messages in ANY language and extract structured service requests. The system works globally — users can request services from any location.

LANGUAGE HANDLING:
- Understand any language the user writes in (English, Urdu, Roman Urdu, Hindi, Arabic, Spanish, etc.)
- Handle code-switching: "AC bilkul kaam nahi kar raha, need technician ASAP"
- Handle misspellings: "electrition", "plumer", "mecanic", "beautishan"
- Handle slang and informal descriptions: "bijli ka masla", "pani leak ho raha", "my lights are flickering"
- Handle abbreviations: "tmrw", "ASAP", "AC", "UPS"

SERVICE CATEGORIES (map user problems to these):
- "ac repair" — AC, cooling, heating, HVAC, air conditioning not working
- "electrician" — bijli, wiring, lights, switches, generator, UPS, solar, power outage, flickering lights, circuit breaker
- "plumber" — pani, pipe, leak, nalkay, bathroom, toilet, drainage, faucet, water heater, clogged drain
- "beautician" — makeup, facial, hair, mehndi, bridal, spa, grooming
- "mechanic" — gaari, car, bike, engine, tire, battery, oil change, brake, car won't start
- "tutor" — padhai, teacher, tuition, coaching, maths, science, homework help
- "carpenter" — furniture, woodwork, cabinet, shelf, door repair, wood
- "painter" — wall painting, house paint, whitewash, interior paint
- "cleaning" — house cleaning, deep clean, maid service, office cleaning
- "pest control" — cockroaches, termites, rats, fumigation, insects
- "locksmith" — locked out, key, lock repair, door lock, safe
- "appliance repair" — washing machine, fridge, refrigerator, microwave, oven repair

IMPORTANT: If the user describes a problem (e.g., "my faucet is dripping"), map it to the correct service category (plumber). Focus on WHAT they need fixed, not how they describe it.

URGENCY DETECTION:
- "emergency"/"foran"/"abhi"/"right now" → "emergency"
- "ASAP"/"jaldi"/"urgent"/"today" → "high"
- "kal"/"tomorrow"/"this week"/"soon" → "medium"
- "koi jaldi nahi"/"whenever"/"flexible"/"no rush" → "low"

COMPLEXITY CLASSIFICATION:
- "basic" — simple tasks (cleaning, minor fix, basic checkup, single item)
- "intermediate" — moderate skill (installation, replacement, moderate repair)
- "complex" — expert needed (compressor repair, complete rewiring, engine overhaul, full renovation)

SENTIMENT DETECTION:
- "frustrated" — complaints, strong negative words, exclamation marks
- "urgent" — time pressure, emergency language
- "calm" — normal request
- "neutral" — unclear tone

LOCATION: Extract any location/address mentioned. If no location is mentioned, set to "unspecified" — the system will use the user's GPS coordinates automatically.

Return ONLY a valid JSON object with these fields:
{
  "service_type": "lowercase category from the list above",
  "location": "area name or 'unspecified'",
  "urgency": "low/medium/high/emergency",
  "preferred_time": "extracted time preference or 'flexible'",
  "preferred_date": "extracted date or 'today'",
  "budget_sensitivity": "high/medium/low",
  "complexity": "basic/intermediate/complex",
  "constraints": ["list of special requirements"],
  "user_preferences": ["list of preferences"],
  "confidence_score": 0-100,
  "clarification_questions": ["questions to ask if confidence < 70"],
  "original_language": "detected language",
  "sentiment": "frustrated/neutral/urgent/calm"
}

IMPORTANT RULES:
1. ALWAYS return valid JSON, nothing else.
2. If you're unsure about service_type, set confidence_score below 60 and add clarification questions.
3. Map informal problem descriptions to the correct service category.
4. "budget zyada nahi hai" / "cheap" / "kam rate" → budget_sensitivity = "high"
5. "paise ki fikr nahi" / "best quality" / "money no issue" → budget_sensitivity = "low"
6. Detect date relative to today's context.
"""


async def extract_intent(
    client: AsyncOpenAI,
    model: str,
    user_message: str,
) -> ExtractedIntent:
    """
    Extract structured intent from a multilingual user message.
    Uses Antigravity LLM for understanding with full trace logging.
    """
    if not _client_has_api_key(client):
        intent = _heuristic_extract_intent(user_message)
        log_trace(
            stage="nlu_local_fallback",
            input_data={"user_message": user_message},
            reasoning=(
                "No Groq API key is configured, so local keyword parsing was used. "
                f"Detected service_type='{intent.service_type}', location='{intent.location}', "
                f"urgency='{intent.urgency}', confidence={intent.confidence_score}%."
            ),
            confidence=intent.confidence_score,
            output_data=intent,
            metadata={"mode": "local_fallback"},
        )
        return intent

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)

        # Normalize confidence score to 0-100
        if parsed.get("confidence_score", 0) <= 1.0:
            parsed["confidence_score"] = parsed["confidence_score"] * 100

        intent = ExtractedIntent(**parsed)

        # Log Antigravity trace
        log_trace(
            stage="nlu_parsing",
            input_data={"user_message": user_message},
            reasoning=(
                f"Detected language: {intent.original_language}. "
                f"Extracted service_type='{intent.service_type}', location='{intent.location}', "
                f"urgency='{intent.urgency}', complexity='{intent.complexity}', "
                f"sentiment='{intent.sentiment}'. "
                f"Confidence: {intent.confidence_score}%."
            ),
            confidence=intent.confidence_score,
            output_data=intent,
            metadata={
                "model": model,
                "input_length": len(user_message),
            },
        )

        return intent

    except Exception as e:
        logger.error(f"NLU extraction failed: {e}")
        intent = _heuristic_extract_intent(user_message)
        log_trace(
            stage="nlu_parsing",
            input_data={"user_message": user_message},
            reasoning=(
                f"NLU extraction failed: {str(e)}. "
                f"Used local fallback with service_type='{intent.service_type}' and confidence={intent.confidence_score}%."
            ),
            confidence=intent.confidence_score,
            output_data=intent,
            metadata={"error": str(e)},
        )
        return intent


def normalize_location(location_name: str) -> dict | None:
    """
    Map informal location names to GPS coordinates.
    Returns {"lat": float, "lng": float, "full_name": str} or None.
    """
    if not location_name or location_name.lower() in ("unspecified", "unknown", ""):
        return None

    # Direct match (case-insensitive)
    for key, coords in LOCATION_COORDS.items():
        if key.lower() == location_name.lower():
            log_trace(
                stage="location_normalization",
                input_data={"location_name": location_name},
                reasoning=f"Direct match found: '{location_name}' → {coords['full_name']}",
                confidence=95,
                output_data=coords,
            )
            return coords

    # Partial match
    for key, coords in LOCATION_COORDS.items():
        if key.lower() in location_name.lower() or location_name.lower() in key.lower():
            log_trace(
                stage="location_normalization",
                input_data={"location_name": location_name},
                reasoning=f"Partial match: '{location_name}' → {coords['full_name']}",
                confidence=80,
                output_data=coords,
            )
            return coords

    # Dynamic geocoding fallback
    try:
        from matcher import MAPS_API_KEY
        if MAPS_API_KEY and MAPS_API_KEY != "your_google_maps_key_here":
            import requests
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {"address": f"{location_name}, Islamabad, Pakistan", "key": MAPS_API_KEY}
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            if data.get("results"):
                res = data["results"][0]
                loc = res["geometry"]["location"]
                coords = {"lat": loc["lat"], "lng": loc["lng"], "full_name": res.get("formatted_address", location_name)}
                log_trace(
                    stage="location_normalization",
                    input_data={"location_name": location_name},
                    reasoning=f"Geocoded via Google Maps: '{location_name}' → {coords['full_name']}",
                    confidence=90,
                    output_data=coords,
                )
                return coords
    except Exception as e:
        logger.error(f"Geocoding fallback failed for '{location_name}': {e}")

    log_trace(
        stage="location_normalization",
        input_data={"location_name": location_name},
        reasoning=f"No location match for '{location_name}'. Using user GPS coordinates as fallback.",
        confidence=30,
    )
    return None


async def generate_clarification(
    client: AsyncOpenAI,
    model: str,
    user_message: str,
    intent: ExtractedIntent,
) -> list[str]:
    """Generate follow-up clarification questions when confidence is low."""
    if not _client_has_api_key(client):
        return intent.clarification_questions or [
            "Could you please tell me what service you need?",
            "Please describe the problem in one more sentence.",
        ]

    prompt = f"""The user said: "{user_message}"
We extracted intent with {intent.confidence_score}% confidence.
Current understanding: service_type="{intent.service_type}", location="{intent.location}"

Generate 2-3 SHORT clarification questions in both English and Roman Urdu to confirm what the user needs.
Return as a JSON array of strings."""

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return a JSON object with key 'questions' containing an array of strings."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        questions = parsed.get("questions", [])

        log_trace(
            stage="clarification_generation",
            input_data={"user_message": user_message, "confidence": intent.confidence_score},
            reasoning=f"Generated {len(questions)} clarification questions due to low confidence ({intent.confidence_score}%).",
            confidence=intent.confidence_score,
            output_data=questions,
        )
        return questions
    except Exception as e:
        logger.error(f"Clarification generation failed: {e}")
        return intent.clarification_questions or [
            "Could you please tell me what service you need?",
            "Kya aap bata sakte hain ke aapko kya service chahiye?",
        ]
