from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .config import get_ai_settings


DEFAULT_THRESHOLDS = {
    "waiver": {"score_min": 12.0, "confidence_min": 0.65, "faab_cap_pct": 0.25}
}


def get_thresholds() -> Dict[str, Any]:
    # Read from env JSON if set via AI_THRESHOLDS_JSON; otherwise defaults
    import os

    raw = os.getenv("AI_THRESHOLDS_JSON")
    if not raw:
        return DEFAULT_THRESHOLDS
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return DEFAULT_THRESHOLDS
        return data
    except Exception:
        return DEFAULT_THRESHOLDS


def can_execute_waiver(score: float, confidence: Optional[float], faab_bid: float, faab_total: Optional[float]) -> bool:
    t = get_thresholds()["waiver"]
    if score < float(t.get("score_min", 0)):
        return False
    if confidence is not None and confidence < float(t.get("confidence_min", 0)):
        return False
    if faab_total and faab_total > 0:
        cap = float(t.get("faab_cap_pct", 1.0)) * float(faab_total)
        if faab_bid > cap:
            return False
    return True


__all__ = ["get_thresholds", "can_execute_waiver"]


