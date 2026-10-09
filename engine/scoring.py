"""Shared scoring helpers: factor scaling, logistic scores, learned weights."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import config


def scale(value: float, cap: float) -> float:
    """Map a non-negative factor to 0..1 (values beyond ``cap`` saturate)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    return max(0.0, min(float(value) / cap, 1.0))


def logistic_score(scaled: dict[str, float], weights: dict[str, float]) -> float:
    """0-100 score = 100 * sigmoid(bias + sum(w * factor))."""
    z = weights.get("bias", 0.0) + sum(weights.get(k, 0.0) * v for k, v in scaled.items())
    return 100.0 / (1.0 + math.exp(-z))


@lru_cache(maxsize=4)
def load_weights(path: str = config.ZONE_WEIGHTS_PATH) -> dict:
    """Learned weights from Backtest 1, falling back to config defaults."""
    defaults = {"strength": dict(config.STRENGTH_WEIGHTS), "break": dict(config.BREAK_WEIGHTS),
                "w_s": config.ZONE_W_STRENGTH, "w_b": config.ZONE_W_BREAK, "source": "config"}
    p = Path(path)
    if not p.exists():
        return defaults
    learned = json.loads(p.read_text())
    return {**defaults, **learned, "source": str(p)}


def raw_to_score(raw, weights: dict):
    """Map raw quality (w_s * strength - w_b * break risk) to the 0-100 score.

    With learned weights the score is the raw value's percentile among TRAIN
    touches (80 = better than 80% of training zones), so the bands are always
    populated. Without them (config defaults) it is the raw value clipped.
    Accepts a float or an array.
    """
    import numpy as np
    q = weights.get("raw_quantiles")
    if q:
        return np.interp(raw, q, np.linspace(0.0, 100.0, len(q)))
    return np.clip(raw, 0.0, 100.0)


def zone_score(strength: float, break_risk: float, w_s: float | None = None, w_b: float | None = None) -> float:
    """Score shown on charts: percentile of w_s * strength - w_b * break risk (see raw_to_score)."""
    w = load_weights()
    w_s = w["w_s"] if w_s is None else w_s
    w_b = w["w_b"] if w_b is None else w_b
    return float(raw_to_score(w_s * strength - w_b * break_risk, w))


def score_band(score: float) -> str:
    if score >= config.ZONE_SCORE_STRONG:
        return "strong"
    if score >= config.ZONE_SCORE_MEDIUM:
        return "medium"
    return "weak"
