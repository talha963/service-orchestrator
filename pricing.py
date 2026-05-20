"""
Dynamic Pricing Engine — Calculates transparent price with full breakdown.
Factors: base rate, distance, urgency, complexity, demand surge, loyalty discount, fairness floor.
"""
import logging
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from trace_logger import log_trace

logger = logging.getLogger("orchestrator.pricing")


class PriceBreakdown(BaseModel):
    base_rate: int = Field(description="Provider's base service rate")
    distance_surcharge: int = Field(default=0, description="Distance-based cost")
    urgency_premium: int = Field(default=0, description="Urgency markup")
    complexity_addon: int = Field(default=0, description="Complexity-based addition")
    demand_surge: int = Field(default=0, description="Demand-based surge pricing")
    loyalty_discount: int = Field(default=0, description="Returning customer discount")
    total: int = Field(description="Final price")
    currency: str = Field(default="PKR")
    fairness_note: str = Field(default="", description="Explanation of price fairness")
    budget_alternative: Optional[dict] = Field(default=None, description="Cheaper option if available")


# Surge multipliers by demand level
SURGE_LEVELS = {
    "low": 0,       # No surge
    "normal": 0,    # No surge
    "moderate": 0.10,  # 10% surge
    "high": 0.20,   # 20% surge
    "peak": 0.35,   # 35% surge
}

# Minimum earning floor for providers (ensure fair wage)
MIN_PROVIDER_EARNING = 500  # PKR


def calculate_price(
    provider: dict,
    distance_km: float,
    urgency: str,
    complexity: str,
    budget_sensitivity: str,
    is_returning_customer: bool = False,
    demand_level: str = "normal",
    all_candidates: list[dict] | None = None,
) -> PriceBreakdown:
    """
    Calculate a dynamic price with transparent breakdown.
    """
    base_rate = provider.get("base_rate", 1000)

    # 1. Distance Surcharge: Rs. 60/km for distances > 2km
    distance_cost = max(0, int((distance_km - 2) * 60)) if distance_km > 2 else 0

    # 2. Urgency Premium
    urgency_rates = {
        "low": 0,
        "medium": 0,
        "high": 0.15,      # 15%
        "emergency": 0.30,  # 30%
    }
    urgency_pct = urgency_rates.get(urgency.lower(), 0)
    urgency_premium = int(base_rate * urgency_pct)

    # 3. Complexity Add-on
    complexity_rates = {
        "basic": 0,
        "intermediate": 500,
        "complex": 1000,
    }
    complexity_addon = complexity_rates.get(complexity.lower(), 0)

    # 4. Demand Surge
    surge_pct = SURGE_LEVELS.get(demand_level, 0)
    subtotal = base_rate + distance_cost + urgency_premium + complexity_addon
    demand_surge = int(subtotal * surge_pct)

    # 5. Loyalty Discount
    loyalty_discount = 0
    if is_returning_customer:
        loyalty_discount = int(subtotal * 0.10)  # 10% off for returning customers

    # Calculate total
    total = subtotal + demand_surge - loyalty_discount

    # 6. Fairness Floor — ensure provider earns minimum
    if total < MIN_PROVIDER_EARNING:
        total = MIN_PROVIDER_EARNING

    # Generate fairness note
    fairness_note = _generate_fairness_note(
        base_rate, distance_cost, urgency_premium, complexity_addon,
        demand_surge, loyalty_discount, total, budget_sensitivity, provider
    )

    # Find budget alternative if user is price-sensitive
    budget_alt = None
    if budget_sensitivity == "high" and all_candidates:
        budget_alt = _find_budget_alternative(
            provider, all_candidates, distance_km, urgency, complexity
        )

    breakdown = PriceBreakdown(
        base_rate=base_rate,
        distance_surcharge=distance_cost,
        urgency_premium=urgency_premium,
        complexity_addon=complexity_addon,
        demand_surge=demand_surge,
        loyalty_discount=loyalty_discount,
        total=total,
        fairness_note=fairness_note,
        budget_alternative=budget_alt,
    )

    log_trace(
        stage="dynamic_pricing",
        input_data={
            "provider": provider["name"],
            "base_rate": base_rate,
            "distance_km": distance_km,
            "urgency": urgency,
            "complexity": complexity,
            "demand_level": demand_level,
            "budget_sensitivity": budget_sensitivity,
        },
        reasoning=(
            f"Price for {provider['name']}: Base Rs.{base_rate} + "
            f"Distance Rs.{distance_cost} ({distance_km}km) + "
            f"Urgency Rs.{urgency_premium} ({urgency}) + "
            f"Complexity Rs.{complexity_addon} ({complexity}) + "
            f"Surge Rs.{demand_surge} ({demand_level}) - "
            f"Loyalty Rs.{loyalty_discount} = Total Rs.{total}"
        ),
        confidence=95,
        output_data=breakdown,
    )

    return breakdown


def _generate_fairness_note(
    base_rate, distance_cost, urgency_premium, complexity_addon,
    demand_surge, loyalty_discount, total, budget_sensitivity, provider
) -> str:
    """Generate a human-readable fairness explanation."""
    parts = [f"Base service rate: Rs. {base_rate}"]

    if distance_cost > 0:
        parts.append(f"Travel cost added for distance")
    if urgency_premium > 0:
        parts.append(f"Urgency premium applied due to time-sensitive request")
    if complexity_addon > 0:
        parts.append(f"Complex job requires specialist equipment/skills")
    if demand_surge > 0:
        parts.append(f"Current demand is elevated in your area")
    if loyalty_discount > 0:
        parts.append(f"10% returning customer discount applied")

    if budget_sensitivity == "high":
        parts.append("We've optimized for your budget while maintaining quality")

    parts.append(
        f"Provider {provider['name']} has {provider.get('rating', 'N/A')} rating "
        f"with {provider.get('on_time_percentage', 'N/A')}% on-time record"
    )

    return ". ".join(parts) + "."


def _find_budget_alternative(
    primary_provider: dict,
    all_candidates: list[dict],
    distance_km: float,
    urgency: str,
    complexity: str,
) -> dict | None:
    """Find a cheaper alternative for budget-sensitive users."""
    cheaper_options = [
        c for c in all_candidates
        if c["provider"]["id"] != primary_provider["id"]
        and c["provider"].get("base_rate", 9999) < primary_provider.get("base_rate", 0)
        and c["provider"].get("rating", 0) >= 3.5  # Minimum quality threshold
    ]

    if not cheaper_options:
        return None

    # Pick the cheapest viable option
    cheapest = min(cheaper_options, key=lambda x: x["provider"]["base_rate"])
    alt_provider = cheapest["provider"]
    alt_total = (
        alt_provider["base_rate"]
        + max(0, int((cheapest.get("dist", 5) - 2) * 60))
    )

    savings = primary_provider["base_rate"] - alt_provider["base_rate"]

    log_trace(
        stage="budget_alternative",
        input_data={"primary": primary_provider["name"], "alternative": alt_provider["name"]},
        reasoning=(
            f"Budget alternative found: {alt_provider['name']} at Rs.{alt_total} "
            f"(saves Rs.{savings}). Rating: {alt_provider['rating']} "
            f"(vs {primary_provider['rating']} for primary). "
            f"Trade-off: Lower cost but {alt_provider.get('on_time_percentage', 'N/A')}% reliability."
        ),
        confidence=85,
    )

    return {
        "provider_name": alt_provider["name"],
        "estimated_price": alt_total,
        "rating": alt_provider["rating"],
        "savings": savings,
        "trade_off": f"Rating {alt_provider['rating']} vs {primary_provider['rating']}, "
                     f"reliability {alt_provider.get('on_time_percentage', 'N/A')}%",
    }


def estimate_demand_level(service_type: str, hour: int) -> str:
    """Estimate demand level based on service type and time of day."""
    # Peak hours for different services
    peak_hours = {
        "ac repair": [10, 11, 12, 13, 14, 15],  # Hot afternoon hours
        "electrician": [18, 19, 20, 21],          # Evening power issues
        "plumber": [7, 8, 9, 10],                 # Morning plumbing issues
        "beautician": [16, 17, 18, 19],           # Evening/event prep
        "mechanic": [8, 9, 10, 17, 18],           # Morning/evening commute
        "tutor": [15, 16, 17, 18],                # After school
    }

    service_peaks = peak_hours.get(service_type.lower(), [])

    if hour in service_peaks:
        return "high"
    elif abs(min((abs(hour - h) for h in service_peaks), default=99)) <= 1:
        return "moderate"
    else:
        return "normal"
