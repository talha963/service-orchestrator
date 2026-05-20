"""
Provider-Side Optimization — Workload balancing, demand forecasting,
recommended time slots, and fair earning analysis.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from trace_logger import log_trace

logger = logging.getLogger("orchestrator.provider_optimizer")

BASE_DIR = Path(__file__).resolve().parent
PROVIDERS_FILE = BASE_DIR / "data" / "providers.json"
BOOKINGS_FILE = BASE_DIR / "data" / "bookings_db.json"


def _load_providers():
    try:
        with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _load_bookings():
    try:
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_workload_dashboard():
    providers = _load_providers()
    bookings = _load_bookings()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dashboard = {"generated_at": datetime.now(timezone.utc).isoformat(), "total_providers": len(providers), "providers": [], "service_summary": {}, "recommendations": []}
    service_stats = defaultdict(lambda: {"providers": 0, "total_load": 0, "total_capacity": 0})

    for p in providers:
        today_bk = [b for b in bookings if b.get("provider_id") == p["id"] and b.get("scheduled_date") == today and b.get("status") in ("confirmed", "in_progress")]
        load = len(today_bk)
        cap = p.get("capacity_per_day", 4)
        util = round((load / cap) * 100, 1) if cap > 0 else 0
        today_earn = sum(b.get("price_total", 0) for b in today_bk)
        all_bk = [b for b in bookings if b.get("provider_id") == p["id"] and b.get("status") in ("completed", "confirmed", "in_progress")]
        total_earn = sum(b.get("price_total", 0) for b in all_bk)
        pd = {"id": p["id"], "name": p["name"], "service": p["service"], "current_load": load, "capacity": cap, "utilization_pct": util, "today_earnings": today_earn, "total_earnings": total_earn, "rating": p.get("rating", 0), "risk_score": p.get("risk_score", 0), "status": "overloaded" if util > 90 else "busy" if util > 60 else "available"}
        dashboard["providers"].append(pd)
        svc = p["service"]
        service_stats[svc]["providers"] += 1
        service_stats[svc]["total_load"] += load
        service_stats[svc]["total_capacity"] += cap

    for svc, stats in service_stats.items():
        util = round((stats["total_load"] / stats["total_capacity"]) * 100, 1) if stats["total_capacity"] > 0 else 0
        dashboard["service_summary"][svc] = {"providers": stats["providers"], "total_load": stats["total_load"], "total_capacity": stats["total_capacity"], "utilization_pct": util}

    # Recommendations
    for prov in dashboard["providers"]:
        if prov["utilization_pct"] > 90:
            dashboard["recommendations"].append({"type": "overload_warning", "provider": prov["name"], "message": f"{prov['name']} at {prov['utilization_pct']}% capacity.", "priority": "high"})
        elif prov["utilization_pct"] == 0:
            dashboard["recommendations"].append({"type": "underutilized", "provider": prov["name"], "message": f"{prov['name']} has no jobs today.", "priority": "medium"})

    log_trace(stage="workload_analysis", input_data={"date": today}, reasoning=f"Workload dashboard: {len(providers)} providers analyzed.", confidence=95, output_data={"providers_count": len(providers)})
    return dashboard


def get_demand_forecast(service_type=None):
    bookings = _load_bookings()
    day_patterns = defaultdict(lambda: defaultdict(int))
    for b in bookings:
        try:
            ds = b.get("scheduled_date", "")
            hour = b.get("scheduled_hour", 10)
            if ds:
                date = datetime.strptime(ds, "%Y-%m-%d")
                day = date.strftime("%A").lower()
                day_patterns[day][hour] += 1
        except Exception:
            continue

    peak_times = {}
    for day, hours in day_patterns.items():
        if hours:
            peak_hour = max(hours, key=hours.get)
            peak_times[day] = {"peak_hour": peak_hour, "count": hours[peak_hour]}

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "peak_times_by_day": peak_times, "recommendations": ["Morning 8-11 AM: high demand for AC/plumbing", "Evening 4-7 PM: tutoring/beautician peak", "Weekends: 20-30% lower demand", "Fridays: reduced availability"]}


def get_recommended_slots(provider_id):
    providers = _load_providers()
    provider = next((p for p in providers if p["id"] == provider_id), None)
    if not provider:
        return {"error": "Provider not found"}

    bookings = _load_bookings()
    hour_demand = defaultdict(int)
    for b in bookings:
        if b.get("service_type", "").lower() == provider["service"].lower():
            hour_demand[b.get("scheduled_hour", 10)] += 1

    avg_rate = provider.get("base_rate", 1000)
    available_slots = provider.get("capacity_per_day", 4) - provider.get("current_load", 0)
    return {"provider": provider["name"], "service": provider["service"], "earning_potential_today": available_slots * avg_rate, "available_slots_today": available_slots, "tips": [f"{available_slots} open slots at Rs.{avg_rate}/job avg", f"On-time score ({provider.get('on_time_percentage', 0)}%) affects ranking"]}


def get_fair_earning_analysis():
    providers = _load_providers()
    bookings = _load_bookings()
    earnings = {}
    for p in providers:
        pb = [b for b in bookings if b.get("provider_id") == p["id"] and b.get("status") in ("completed", "confirmed")]
        total = sum(b.get("price_total", 0) for b in pb)
        earnings[p["id"]] = {"name": p["name"], "service": p["service"], "total_earnings": total, "job_count": len(pb), "rating": p.get("rating", 0)}

    all_e = [e["total_earnings"] for e in earnings.values()]
    avg_e = round(sum(all_e) / len(all_e), 0) if all_e else 0
    max_e = max(all_e) if all_e else 0
    min_e = min(all_e) if all_e else 0
    fairness = round((1 - (max_e - min_e) / max_e) * 100, 1) if max_e > 0 else 100

    return {"provider_earnings": earnings, "summary": {"average": avg_e, "max": max_e, "min": min_e, "fairness_score": fairness, "note": "Fair" if fairness > 70 else "Imbalanced"}}
