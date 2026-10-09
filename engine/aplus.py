"""Module 6 — A+ score 0-7: seven checks that must line up for the best setups."""
from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class APlus:
    score: int
    checks: dict[str, bool]

    @property
    def grade(self) -> str:
        if self.score >= config.APLUS_GRADE:
            return "A+"
        if self.score >= config.A_GRADE:
            return "A"
        return "B"


def aplus_score(direction: str, *, catalyst: bool, confluence: bool, slow_bull_5m: bool,
                slow_bull_10m: bool, confirmed: bool, rvol: float, r_to_t1: float,
                market_against: bool) -> APlus:
    """Score a setup. Clouds agree = 5m and 10m 34/50 clouds both point the trade's way."""
    want = direction == "long"
    checks = {
        "catalyst": bool(catalyst),
        "level_confluence": bool(confluence),
        "clouds_agree": slow_bull_5m == want and slow_bull_10m == want,
        "5m_confirmation": bool(confirmed),
        "rvol": rvol == rvol and rvol >= config.APLUS_MIN_RVOL,
        "r_to_t1": r_to_t1 >= config.MIN_R_TO_T1_APLUS,
        "market_not_against": not market_against,
    }
    return APlus(sum(checks.values()), checks)
