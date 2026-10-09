"""Re-planner (on regime change, gap fill, VWAP lost/reclaimed, cloud flip, big news)
and the 8:30 premarket planner. Prices may only come from ``allowed_prices``."""
from __future__ import annotations

from ai.client import AIClient, load_prompt
from ai.schemas import PremarketPlan, Replan


def allowed_levels(zones: list[dict], atr: float, extra: list[float] = ()) -> list[float]:
    """Zone edges, edges ± 0.1 ATR (stop/front-run buffers) and any extra levels."""
    out = set(round(x, 2) for x in extra)
    for z in zones:
        for edge in (z["bottom"], z["top"]):
            out |= {round(edge, 2), round(edge - 0.1 * atr, 2), round(edge + 0.1 * atr, 2)}
    return sorted(out)


def replan(ai: AIClient, symbol: str, profile: dict, zones: list[dict], regime: str,
           position: dict | None, event: dict, recent_events: list[dict]) -> Replan | None:
    allowed = allowed_levels(zones, profile["atr_5m"], [position[k] for k in ("entry", "stop", "t1", "t2")
                                                        if position and k in position])
    payload = {"symbol": symbol, "profile": profile, "zones": zones, "regime": regime, "position": position,
               "event": event, "recent_events": recent_events, "allowed_prices": allowed}
    return ai.ask("replanner", load_prompt("replanner"), payload, Replan, allowed_prices=allowed)


def premarket_plan(ai: AIClient, tickers: dict[str, dict], calendar: list[dict],
                   headlines: list[dict]) -> PremarketPlan | None:
    allowed = sorted({p for t in tickers.values() for p in t["allowed_prices"]})
    payload = {"tickers": tickers, "calendar": calendar, "headlines": headlines, "allowed_prices": allowed}
    return ai.ask("premarket", load_prompt("premarket"), payload, PremarketPlan, allowed_prices=allowed)
