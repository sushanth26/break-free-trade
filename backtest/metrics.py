"""Trade metrics and the pass criteria. Win = T1 hit before the stop; R = P&L / initial risk."""
from __future__ import annotations

import math

import pandas as pd

import config


def filled(trades: pd.DataFrame) -> pd.DataFrame:
    if len(trades) == 0 or "state" not in trades:
        return trades.iloc[0:0]
    return trades[trades["state"] == "closed"]


def win_rate_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for the win rate (normal approximation, as in the plan: ±6.7 pts at 200 trades)."""
    if n == 0:
        return float("nan"), float("nan")
    p = wins / n
    half = z * math.sqrt(p * (1 - p) / n)
    return max(0.0, p - half), min(1.0, p + half)


def max_drawdown_r(r: pd.Series) -> float:
    curve = r.cumsum()
    return float((curve.cummax() - curve).max()) if len(curve) else 0.0


def summarize(trades: pd.DataFrame) -> dict:
    t = filled(trades)
    n = len(t)
    if n == 0:
        return {"trades": 0}
    t = t.sort_values("fill_time")
    wins, losses = t[t["win"]], t[~t["win"]]
    win = len(wins) / n
    avg_w = float(wins["r"].mean()) if len(wins) else 0.0
    avg_l = float(-losses["r"].mean()) if len(losses) else 0.0
    gross_w = t.loc[t["r"] > 0, "r"].sum()
    gross_l = -t.loc[t["r"] < 0, "r"].sum()
    lo, hi = win_rate_interval(len(wins), n)
    days = pd.DatetimeIndex(t["fill_time"]).normalize().nunique()
    return {
        "trades": n,
        "win_rate": win,
        "win_rate_low": lo,
        "win_rate_high": hi,
        "avg_win_r": avg_w,
        "avg_loss_r": avg_l,
        "expectancy_r": float(t["r"].mean()),
        "expectancy_worst_r": lo * avg_w - (1 - lo) * avg_l,
        "profit_factor": float(gross_w / gross_l) if gross_l > 0 else float("inf"),
        "max_drawdown_r": max_drawdown_r(t["r"]),
        "trades_per_day": n / days if days else 0.0,
        "total_r": float(t["r"].sum()),
        "fill_rate": n / len(trades) if len(trades) else float("nan"),
    }


def breakdown(trades: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    t = filled(trades)
    if t.empty:
        return pd.DataFrame()
    rows = []
    for key, g in t.groupby(by):
        rows.append({"group": key, **summarize(g)})
    return pd.DataFrame(rows).set_index("group")


def add_time_buckets(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.copy()
    if len(out):
        h = pd.DatetimeIndex(out["signal_time"]).strftime("%H:%M")
        out["time_bucket"] = pd.cut(pd.to_timedelta(h + ":00").total_seconds() / 3600,
                                    [0, 9.5, 10.5, 12, 14, 16, 24],
                                    labels=["premarket", "09:30-10:30", "10:30-12", "12-14", "14-16", "after"])
    return out


def passes(summary: dict, min_trades: int = config.PASS_MIN_TRADES) -> dict[str, bool]:
    """Quantitative pass checks (trader chart review is separate and mandatory)."""
    if summary.get("trades", 0) == 0:
        return {"trades": False}
    return {
        "trades": summary["trades"] >= min_trades,
        "win_rate": summary["win_rate"] >= config.PASS_MIN_WIN_RATE,
        "expectancy_worst": summary["expectancy_worst_r"] >= config.PASS_MIN_EXPECTANCY_R,
        "profit_factor": summary["profit_factor"] >= config.PASS_MIN_PROFIT_FACTOR,
        "max_drawdown": summary["max_drawdown_r"] <= config.PASS_MAX_DRAWDOWN_R,
    }
