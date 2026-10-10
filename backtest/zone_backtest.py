"""Day 3 — Backtest 1: zone quality over 144 configs, learned score weights.

8 timeframe combos x 18 settings (pivot period x channel width x min
strength). For each config and stock, every zone touch is labelled
(backtest/labels.py); configs are compared on hold rate, reaction size,
overshoot, zones per day and distance from price. Logistic regression on
TRAIN touches learns the strength and break-risk weights and their balance.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import config
from backtest.labels import ZoneTimeline, find_touches
from backtest.split import is_oos, is_train
from config import ZoneConfig
from data.base import extended_hours, regular_hours, resample, to_ts
from engine.break_risk import scale_break
from engine.features import compute_features
from engine.profile import round_step
from engine.strength import scale_strength
from engine.zones import merge_zones, zone_history, zones_at


@dataclass
class SymbolData:
    symbol: str
    bars: pd.DataFrame          # 5m bars (extended hours allowed)
    daily: pd.DataFrame
    feats: pd.DataFrame | None = None

    def __post_init__(self):
        if self.feats is None:
            self.feats = compute_features(self.bars, self.daily)
        self._rows = None

    @property
    def rows(self):
        if self._rows is None:
            from engine.features import feature_rows
            self._rows = feature_rows(self.feats)
        return self._rows


def config_grid() -> list[tuple[tuple[str, ...], ZoneConfig]]:
    settings = [ZoneConfig(pivot_period=p, channel_width_pct=w, min_strength=s)
                for p, w, s in itertools.product(config.ZONE_GRID_PIVOT_PERIODS,
                                                 config.ZONE_GRID_CHANNEL_WIDTHS,
                                                 config.ZONE_GRID_MIN_STRENGTHS)]
    return [(combo, cfg) for combo in config.ZONE_GRID_TIMEFRAME_COMBOS for cfg in settings]


def config_id(combo: tuple[str, ...], cfg: ZoneConfig) -> str:
    return f"{'+'.join(combo)}|p{cfg.pivot_period}|w{cfg.channel_width_pct:g}|s{cfg.min_strength}"


def build_timeline(data: SymbolData, combo: tuple[str, ...], cfg: ZoneConfig,
                   cache: dict | None = None, session: str = "regular") -> ZoneTimeline:
    """Merged multi-timeframe zone sets over time (changes only at pivot confirmations).

    ``session``: "regular" (09:30-16:00, the default everywhere this was already
    used) or "extended" (04:00-20:00 -- as far as our data goes; a trader's
    TradingView chart may show true overnight bars we don't have at all).
    """
    cache = {} if cache is None else cache
    reg = regular_hours(data.bars) if session == "regular" else extended_hours(data.bars)
    histories = []
    for tf in combo:
        key = (data.symbol, tf, cfg, session)
        if key not in cache:
            src = reg if tf == "5m" else data.daily if tf == "D" else resample(reg, tf, regular_only=False)
            cache[key] = zone_history(src, tf, cfg)
        histories.append(cache[key])
    times = sorted({t for h in histories for t, _ in h})
    sets = []
    for t in times:
        zones = [z for h in histories for z in zones_at(h, t)]
        sets.append(merge_zones(zones) if len(combo) > 1 else zones)
    return ZoneTimeline(times, sets)


def zone_presence(data: SymbolData, timeline: ZoneTimeline, sample_every: int = 12) -> tuple[float, float]:
    """(average zones in force, average distance of the nearest zone in ATR), sampled hourly."""
    reg = data.feats[data.feats["regular"]].iloc[::sample_every]
    counts, dists = [], []
    for t, row in reg.iterrows():
        zones = timeline(t + pd.Timedelta("5min"))
        counts.append(len(zones))
        if zones and row["atr"] > 0:
            dists.append(min(abs(row["close"] - z.mid) for z in zones) / row["atr"])
    return float(np.mean(counts)) if counts else 0.0, float(np.mean(dists)) if dists else float("nan")


def run_config(datas: list[SymbolData], combo, cfg, regime: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    frames = []
    cache: dict = {}
    for d in datas:
        tl = build_timeline(d, combo, cfg, cache)
        step = round_step(float(d.bars["close"].iloc[-1]))
        t = find_touches(d.bars, d.feats, tl, step, (regime or {}).get(d.symbol), d.symbol)
        if len(t):
            n_zones, dist = zone_presence(d, tl)
            t["zones_in_force"], t["nearest_zone_atr"] = n_zones, dist
            frames.append(t)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(out):
        out["config"] = config_id(combo, cfg)
    return out


def summarize(touches: pd.DataFrame) -> dict:
    """Metrics for one config's labelled touches (resolved touches only)."""
    r = touches[touches["outcome"] != "none"]
    days = touches["time"].dt.normalize().nunique() if len(touches) else 0
    return {
        "touches": len(r),
        "hold_rate": float(r["held"].mean()) if len(r) else float("nan"),
        "reaction_atr": float(r.loc[r["held"], "reaction_atr"].mean()) if r["held"].any() else float("nan"),
        "overshoot_atr": float(r["overshoot_atr"].mean()) if len(r) else float("nan"),
        "touches_per_day": len(r) / days if days else 0.0,
        "zones_in_force": float(touches["zones_in_force"].mean()) if len(touches) else 0.0,
        "nearest_zone_atr": float(touches["nearest_zone_atr"].mean()) if len(touches) else float("nan"),
    }


def run_grid(datas: list[SymbolData], grid=None, n_jobs: int = 1, min_touches: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All configs → (touches, leaderboard). Leaderboard metrics use TRAIN touches only."""
    grid = grid or config_grid()
    if n_jobs == 1:
        results = [run_config(datas, c, z) for c, z in grid]
    else:
        from joblib import Parallel, delayed
        results = Parallel(n_jobs=n_jobs)(delayed(run_config)(datas, c, z) for c, z in grid)
    touches = pd.concat([r for r in results if len(r)], ignore_index=True) if any(len(r) for r in results) else pd.DataFrame()
    rows = []
    for (combo, cfg), res in zip(grid, results):
        train = res[is_train(pd.DatetimeIndex(res["time"])).to_numpy()] if len(res) else res
        rows.append({"config": config_id(combo, cfg), **summarize(train if len(train) else res.iloc[0:0])})
    board = pd.DataFrame(rows)
    board["eligible"] = board["touches"] >= min_touches
    board = board.sort_values(["eligible", "hold_rate", "reaction_atr"], ascending=False).reset_index(drop=True)
    return touches, board


# ------------------------------------------------------------------ learning weights

def _matrix(touches: pd.DataFrame, prefix: str, scaler) -> pd.DataFrame:
    cols = [c for c in touches.columns if c.startswith(prefix)]
    raw = touches[cols].rename(columns=lambda c: c[len(prefix):])
    return pd.DataFrame([scaler(r) for r in raw.to_dict("records")], index=touches.index)


def learn_weights(touches: pd.DataFrame, C: float = 1.0) -> dict:
    """Fit strength (→ held), break risk (→ broke) and their balance on resolved touches."""
    from sklearn.linear_model import LogisticRegression

    r = touches[touches["outcome"] != "none"]
    if r["held"].nunique() < 2:
        raise ValueError("need both held and broken touches to learn weights")
    y = r["held"].astype(int).to_numpy()
    xs, xb = _matrix(r, "s_", scale_strength), _matrix(r, "b_", scale_break)
    ms = LogisticRegression(C=C, max_iter=1000).fit(xs, y)
    mb = LogisticRegression(C=C, max_iter=1000).fit(xb, 1 - y)
    s = 100 / (1 + np.exp(-ms.decision_function(xs)))
    b = 100 / (1 + np.exp(-mb.decision_function(xb)))
    bal = LogisticRegression(C=C, max_iter=1000).fit(np.c_[s, b] / 100, y)
    a_s, a_b = bal.coef_[0]
    w_s = 1.0
    w_b = float(max(-a_b, 0.0) / a_s) if a_s > 0 else config.ZONE_W_BREAK
    raw = w_s * s - w_b * b
    return {
        "strength": {"bias": float(ms.intercept_[0]), **dict(zip(xs.columns, map(float, ms.coef_[0])))},
        "break": {"bias": float(mb.intercept_[0]), **dict(zip(xb.columns, map(float, mb.coef_[0])))},
        "w_s": w_s, "w_b": w_b, "n_train": int(len(r)),
        "raw_quantiles": [float(v) for v in np.quantile(raw, np.linspace(0, 1, config.ZONE_SCORE_QUANTILES))],
    }


def apply_weights(touches: pd.DataFrame, weights: dict) -> pd.DataFrame:
    from engine.scoring import logistic_score, raw_to_score
    out = touches.copy()
    xs, xb = _matrix(out, "s_", scale_strength), _matrix(out, "b_", scale_break)
    out["strength"] = [logistic_score(r, weights["strength"]) for r in xs.to_dict("records")]
    out["break_risk"] = [logistic_score(r, weights["break"]) for r in xb.to_dict("records")]
    out["score"] = raw_to_score(weights["w_s"] * out["strength"] - weights["w_b"] * out["break_risk"], weights)
    return out


def score_bands(touches: pd.DataFrame) -> pd.DataFrame:
    """Hold rate by score band (80+ should hold far more than under 50)."""
    r = touches[touches["outcome"] != "none"].copy()
    r["band"] = pd.cut(r["score"], [-1, 49.999, 79.999, 101], labels=["<50", "50-79", "80+"])
    return r.groupby("band", observed=False).agg(touches=("held", "size"), hold_rate=("held", "mean"))


def day3_gate(train: pd.DataFrame, valid_start: str = config.ZONE_GATE_VALID_START,
              min_touches: int = config.ZONE_GATE_MIN_TOUCHES, min_edge: float = config.ZONE_GATE_MIN_EDGE) -> dict:
    """Day 3 gate on TRAIN touches only: fit before ``valid_start``, score the rest.

    Passes when the 80+ and <50 bands each have ``min_touches`` validation
    touches and 80+ holds at least ``min_edge`` more often (as a fraction). Out-of-sample touches are never used.
    """
    t = pd.DatetimeIndex(train["time"])
    fit, valid = train[t < to_ts(valid_start)], train[t >= to_ts(valid_start)]
    bands = score_bands(apply_weights(valid, learn_weights(fit)))
    top, low = bands.loc["80+"], bands.loc["<50"]
    enough = top["touches"] >= min_touches and low["touches"] >= min_touches
    edge = float(top["hold_rate"] - low["hold_rate"]) if enough else float("nan")
    return {"bands": bands, "n_fit": len(fit), "n_valid": len(valid), "enough": bool(enough), "edge": edge,
            "passed": bool(enough and edge >= min_edge)}


def save_weights(weights: dict, path: str | Path = config.ZONE_WEIGHTS_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(weights, indent=2))
    from engine.scoring import load_weights
    load_weights.cache_clear()
    return p


def split_touches(touches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = pd.DatetimeIndex(touches["time"])
    return touches[is_train(idx).to_numpy()], touches[is_oos(idx).to_numpy()]
