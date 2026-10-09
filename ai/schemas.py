"""Strict JSON shapes for every Claude role. The SDK validates responses against
these; code then checks the guardrails (allowed prices, reasons)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NewsJudgment(BaseModel):
    relevance: Literal["ticker", "sector", "market", "none"]
    direction: Literal["bullish", "bearish", "neutral"]
    impact: Literal["low", "medium", "high"]
    action: Literal["no_change", "tighten", "flip_bias", "exit"]
    reason: str = Field(description="One line. Required when action is not no_change.")


class Replan(BaseModel):
    action: Literal["no_change", "replan"]
    bias: Literal["long", "short", "wait"]
    entry_zone: str = Field(description="Zone label from the input, e.g. S1, or empty")
    entry: float | None = None
    stop: float | None = None
    t1: float | None = None
    t2: float | None = None
    invalidation: float | None = None
    reason: str = Field(description="One line. Required when action is replan.")


class Scenario(BaseModel):
    ticker: str
    regime: Literal["bullish", "gap_filling", "gap_filled", "choppy"]
    plan: str = Field(description="If/then in one or two short lines, using only given levels")
    levels: list[float]


class PremarketPlan(BaseModel):
    scenarios: list[Scenario]


def prices_in(obj: BaseModel) -> list[float]:
    """Every price a response proposes (None values skipped)."""
    if isinstance(obj, Replan):
        return [x for x in (obj.entry, obj.stop, obj.t1, obj.t2, obj.invalidation) if x is not None]
    if isinstance(obj, PremarketPlan):
        return [x for s in obj.scenarios for x in s.levels]
    return []


def needs_reason(obj: BaseModel) -> bool:
    if isinstance(obj, NewsJudgment):
        return obj.action != "no_change"
    if isinstance(obj, Replan):
        return obj.action != "no_change"
    return False
