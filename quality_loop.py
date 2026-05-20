"""
Service Quality Loop — Feedback collection, sentiment analysis,
rating adjustment, and reputation management.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from openai import AsyncOpenAI
from trace_logger import log_trace

logger = logging.getLogger("orchestrator.quality")

BASE_DIR = Path(__file__).resolve().parent
REPUTATION_FILE = BASE_DIR / "data" / "reputation_log.json"
PROVIDERS_FILE = BASE_DIR / "data" / "providers.json"


def _load_reputation_log() -> list[dict]:
    try:
        with open(REPUTATION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_reputation_log(log: list[dict]):
    with open(REPUTATION_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, default=str)


def _load_providers() -> list[dict]:
    try:
        with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_providers(providers: list[dict]):
    with open(PROVIDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(providers, f, indent=2, default=str)


async def process_feedback(
    client: AsyncOpenAI,
    model: str,
    booking_id: str,
    provider_id: str,
    rating: int,
    review_text: str = "",
) -> dict:
    """
    Process customer feedback: analyze sentiment, adjust rating, update reputation.
    """
    # Analyze sentiment if review text provided
    sentiment = "neutral"
    sentiment_score = 0.5
    if review_text:
        sentiment, sentiment_score = await _analyze_sentiment(client, model, review_text)

    # Load current provider data
    providers = _load_providers()
    provider = None
    for p in providers:
        if p["id"] == provider_id:
            provider = p
            break

    if not provider:
        return {"error": "Provider not found"}

    # Calculate new rating using weighted moving average
    old_rating = provider.get("rating", 4.0)
    review_count = provider.get("review_count", 0)
    new_review_count = review_count + 1

    # Weighted average: recent reviews have more weight
    weight_factor = min(0.3, 1 / (review_count + 1))  # More weight for fewer reviews
    new_rating = round(old_rating * (1 - weight_factor) + rating * weight_factor, 2)

    # Update provider data
    provider["rating"] = new_rating
    provider["review_count"] = new_review_count
    provider["review_recency_days"] = 0  # Just reviewed today

    # Track negative reviews
    if rating <= 2:
        provider["recent_negative_reviews"] = provider.get("recent_negative_reviews", 0) + 1
    elif rating >= 4:
        # Decay negative reviews over time
        provider["recent_negative_reviews"] = max(0, provider.get("recent_negative_reviews", 0) - 1)

    # Update risk score
    provider["risk_score"] = _calculate_risk_score(provider)

    _save_providers(providers)

    # Log reputation event
    event = {
        "event_id": f"REP-{len(_load_reputation_log()) + 1:04d}",
        "booking_id": booking_id,
        "provider_id": provider_id,
        "provider_name": provider["name"],
        "rating_given": rating,
        "review_text": review_text,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "old_rating": old_rating,
        "new_rating": new_rating,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    rep_log = _load_reputation_log()
    rep_log.append(event)
    _save_reputation_log(rep_log)

    # Determine impact on future matching
    matching_impact = _assess_matching_impact(provider, rating, sentiment)

    log_trace(
        stage="quality_feedback",
        input_data={
            "booking_id": booking_id,
            "provider": provider["name"],
            "rating": rating,
            "review_text": review_text,
        },
        reasoning=(
            f"Feedback processed for {provider['name']}: "
            f"Rating {rating}/5 (sentiment: {sentiment}, score: {sentiment_score:.2f}). "
            f"Provider rating adjusted from {old_rating} to {new_rating}. "
            f"Risk score: {provider['risk_score']}. "
            f"Future matching impact: {matching_impact}"
        ),
        confidence=90,
        output_data={
            "old_rating": old_rating,
            "new_rating": new_rating,
            "sentiment": sentiment,
            "matching_impact": matching_impact,
        },
        metadata={"booking_id": booking_id},
    )

    return {
        "status": "feedback_processed",
        "old_rating": old_rating,
        "new_rating": new_rating,
        "sentiment": sentiment,
        "sentiment_score": round(sentiment_score, 2),
        "matching_impact": matching_impact,
        "risk_score": provider["risk_score"],
    }


async def _analyze_sentiment(
    client: AsyncOpenAI,
    model: str,
    review_text: str,
) -> tuple[str, float]:
    """Analyze sentiment of review text using Antigravity LLM."""
    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Analyze the sentiment of this service review. "
                        "Return JSON with: 'sentiment' (positive/neutral/negative) "
                        "and 'score' (0.0 to 1.0 where 1.0 is most positive). "
                        "Handle Urdu, Roman Urdu, and English."
                    ),
                },
                {"role": "user", "content": review_text},
            ],
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)

        sentiment = parsed.get("sentiment", "neutral")
        score = float(parsed.get("score", 0.5))

        log_trace(
            stage="sentiment_analysis",
            input_data={"review_text": review_text},
            reasoning=f"Review sentiment: {sentiment} (score: {score:.2f})",
            confidence=85,
        )

        return sentiment, score

    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return "neutral", 0.5


def _calculate_risk_score(provider: dict) -> int:
    """Calculate provider risk score (0-100, higher = riskier)."""
    risk = 0

    # Cancellation rate impact (0-30 points)
    cancel_rate = provider.get("cancellation_rate", 0)
    risk += min(30, cancel_rate * 2)

    # Recent negative reviews (0-25 points)
    neg_reviews = provider.get("recent_negative_reviews", 0)
    risk += min(25, neg_reviews * 5)

    # Low reliability (0-20 points)
    on_time = provider.get("on_time_percentage", 100)
    if on_time < 90:
        risk += min(20, (90 - on_time))

    # Low rating (0-15 points)
    rating = provider.get("rating", 5.0)
    if rating < 4.0:
        risk += min(15, int((4.0 - rating) * 10))

    # Few completed jobs — less trustworthy (0-10 points)
    jobs = provider.get("jobs_completed", 0)
    if jobs < 50:
        risk += 10
    elif jobs < 100:
        risk += 5

    return min(100, risk)


def _assess_matching_impact(provider: dict, rating: int, sentiment: str) -> str:
    """Describe how this feedback impacts future matching."""
    impacts = []

    if rating >= 4:
        impacts.append("Positive impact: provider will rank higher in future matches")
    elif rating == 3:
        impacts.append("Neutral impact: no significant change in ranking")
    elif rating <= 2:
        impacts.append("Negative impact: provider ranking will decrease")

    if sentiment == "negative":
        impacts.append("Negative sentiment detected — recent_negative_reviews incremented")

    risk = provider.get("risk_score", 0)
    if risk > 50:
        impacts.append(f"HIGH RISK ({risk}/100): Provider may be deprioritized or flagged")
    elif risk > 30:
        impacts.append(f"Moderate risk ({risk}/100): Provider under observation")

    return "; ".join(impacts)


def get_provider_reputation(provider_id: str) -> dict:
    """Get reputation summary for a provider."""
    rep_log = _load_reputation_log()
    events = [e for e in rep_log if e.get("provider_id") == provider_id]

    if not events:
        return {"provider_id": provider_id, "total_reviews": 0, "history": []}

    ratings = [e.get("rating_given", 0) for e in events]
    sentiments = [e.get("sentiment", "neutral") for e in events]

    return {
        "provider_id": provider_id,
        "total_reviews": len(events),
        "average_rating": round(sum(ratings) / len(ratings), 2),
        "positive_count": sentiments.count("positive"),
        "neutral_count": sentiments.count("neutral"),
        "negative_count": sentiments.count("negative"),
        "recent_events": events[-5:],
    }
