"""Tunable engine levers, bundled so backtests can vary them without touching config."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import config
from config import ZoneConfig


@dataclass(frozen=True)
class EngineSettings:
    zone: ZoneConfig = field(default_factory=lambda: config.ZONE_DEFAULT)
    timeframes: tuple[str, ...] = ("5m",)
    entry_mode: str = config.ENTRY_MODE            # "confirmed" | "early"
    min_zone_score: float = config.MIN_ZONE_SCORE
    aplus_only: bool = config.APLUS_ONLY
    require_regime_agree: bool = config.REQUIRE_REGIME_AGREE
    news_filter: bool = config.NEWS_FILTER
    time_filter: tuple[str, str] | None = config.TIME_FILTER
    min_t1_r: float = config.MIN_T1_R
    allow_premarket: bool = True
    allow_short: bool = True

    def with_(self, **kw) -> "EngineSettings":
        return replace(self, **kw)
