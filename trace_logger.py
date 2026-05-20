"""
Antigravity Trace Logger — Records every decision the AI agent makes.
Provides full transparency into intent parsing, provider ranking,
scheduling, pricing, booking, and dispute resolution reasoning.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("orchestrator.trace")

# In-memory trace store (persists for server lifetime)
_traces: list[dict] = []


def log_trace(
    stage: str,
    input_data: Any,
    reasoning: str,
    confidence: float,
    output_data: Any = None,
    alternatives: list[dict] | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Log an Antigravity reasoning trace.

    Args:
        stage: Pipeline stage (e.g., "nlu_parsing", "provider_matching", "pricing")
        input_data: What went into this decision
        reasoning: Human-readable explanation of why this decision was made
        confidence: 0-100 confidence in the decision
        output_data: The result of the decision
        alternatives: Other options that were considered
        metadata: Extra context (latency, model, etc.)
    """
    trace = {
        "trace_id": f"T-{len(_traces) + 1:04d}",
        "stage": stage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input": _safe_serialize(input_data),
        "reasoning": reasoning,
        "confidence": round(confidence, 1),
        "output": _safe_serialize(output_data),
        "alternatives_considered": alternatives or [],
        "metadata": metadata or {},
    }
    _traces.append(trace)
    logger.info(f"ANTIGRAVITY TRACE [{trace['trace_id']}] [{stage}]: {reasoning}")
    return trace


def get_all_traces() -> list[dict]:
    """Return all traces in chronological order."""
    return list(_traces)


def get_traces_by_stage(stage: str) -> list[dict]:
    """Return traces filtered by pipeline stage."""
    return [t for t in _traces if t["stage"] == stage]


def get_traces_by_booking(booking_id: str) -> list[dict]:
    """Return all traces related to a specific booking."""
    return [
        t for t in _traces
        if t.get("metadata", {}).get("booking_id") == booking_id
    ]


def clear_traces():
    """Clear all traces (for testing)."""
    _traces.clear()


def get_recent_traces(limit: int = 50) -> list[dict]:
    """Return the most recent N traces."""
    return _traces[-limit:]


def _safe_serialize(obj: Any) -> Any:
    """Safely convert objects to JSON-serializable format."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(i) for i in obj]
    # Pydantic models
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)
