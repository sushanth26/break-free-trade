"""Day 5 — tune the levers on TRAIN data only, and save/load the chosen settings.

Levers: min zone score, A+ only, confirmed vs early entry, regime agreement,
time-of-day filter, T1 distance, applied to the top zone configs from
Backtest 1. Choice = best worst-case expectancy among settings that meet the
trade-count and profit-factor floors. Neighbours (one lever one step away)
are listed so Day 6 can check they also pass.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

import config
from backtest.metrics import summarize
from backtest.trade_backtest import BacktestInput, run_backtest
from config import ZoneConfig
from engine.settings import EngineSettings

LEVERS: dict[str, list] = {
    "min_zone_score": [50, 65, 80],
    "aplus_only": [False, True],
    "entry_mode": ["confirmed", "early"],
    "require_regime_agree": [True, False],
    "time_filter": [None, ("09:45", "15:00")],
    "min_t1_r": [1.0, 1.5, 2.0],
}
SETTINGS_PATH = "models/engine_settings.json"


def settings_id(s: EngineSettings) -> str:
    z = s.zone
    return (f"{'+'.join(s.timeframes)}|p{z.pivot_period}|w{z.channel_width_pct:g}|s{z.min_strength}"
            f"|score{s.min_zone_score:g}|aplus{int(s.aplus_only)}|{s.entry_mode}|regime{int(s.require_regime_agree)}"
            f"|tf{'-'.join(s.time_filter) if s.time_filter else 'all'}|t1r{s.min_t1_r:g}")


def zone_settings_from_id(cfg_id: str) -> tuple[tuple[str, ...], ZoneConfig]:
    """Parse a Backtest 1 config id like '5m+1h|p10|w2|s1'."""
    tf, p, w, s = cfg_id.split("|")
    return tuple(tf.split("+")), ZoneConfig(pivot_period=int(p[1:]), channel_width_pct=float(w[1:]),
                                            min_strength=int(s[1:]))


def lever_grid(base: EngineSettings, levers: dict[str, list] = LEVERS) -> list[EngineSettings]:
    keys = list(levers)
    return [base.with_(**dict(zip(keys, combo))) for combo in itertools.product(*(levers[k] for k in keys))]


def neighbours(s: EngineSettings, levers: dict[str, list] = LEVERS) -> list[EngineSettings]:
    """Settings that differ from ``s`` in exactly one lever by one step."""
    out = []
    for k, values in levers.items():
        cur = getattr(s, k)
        if cur not in values:
            continue
        i = values.index(cur)
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                out.append(s.with_(**{k: values[j]}))
    return out


def _run_group(inp: BacktestInput, group: list[EngineSettings], start, end, symbols, adverse=False) -> list[dict]:
    from backtest.fills import FillModel
    rows = []
    for s in group:
        trades, _ = run_backtest(inp, s, FillModel(adverse_selection=adverse), start, end, symbols)
        rows.append({"settings_id": settings_id(s), **summarize(trades)})
    return rows


def evaluate(inp: BacktestInput, settings: list[EngineSettings], start=None, end=None,
             symbols: list[str] | None = None, n_jobs: int = 1, adverse: bool = False) -> pd.DataFrame:
    """Summaries for many settings; grouped by zone config so each worker builds zones once."""
    groups: dict[tuple, list[EngineSettings]] = {}
    for s in settings:
        groups.setdefault((s.timeframes, s.zone), []).append(s)
    if n_jobs == 1:
        parts = [_run_group(inp, g, start, end, symbols, adverse) for g in groups.values()]
    else:
        from joblib import Parallel, delayed
        parts = Parallel(n_jobs=n_jobs)(delayed(_run_group)(inp, g, start, end, symbols, adverse)
                                        for g in groups.values())
    return pd.DataFrame([r for p in parts for r in p])


def choose(results: pd.DataFrame, min_trades: int = config.PASS_MIN_TRADES) -> pd.DataFrame:
    """Rank: eligible (trades and PF floors) first, then worst-case expectancy, then win rate."""
    r = results.copy()
    for col in ("trades", "profit_factor", "expectancy_worst_r", "win_rate"):
        if col not in r:
            r[col] = float("nan")
    r["eligible"] = (r["trades"] >= min_trades) & (r["profit_factor"] >= config.PASS_MIN_PROFIT_FACTOR)
    return r.sort_values(["eligible", "expectancy_worst_r", "win_rate"], ascending=False).reset_index(drop=True)


def save_settings(s: EngineSettings, path: str | Path = SETTINGS_PATH, extra: dict | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    d = asdict(s)
    p.write_text(json.dumps({**d, "id": settings_id(s), **(extra or {})}, indent=2, default=list))
    return p


def load_settings(path: str | Path = SETTINGS_PATH) -> EngineSettings:
    p = Path(path)
    if not p.exists():
        return EngineSettings()
    d = json.loads(p.read_text())
    fields = EngineSettings.__dataclass_fields__
    kw = {k: v for k, v in d.items() if k in fields}
    kw["zone"] = ZoneConfig(**d["zone"])
    kw["timeframes"] = tuple(d["timeframes"])
    kw["time_filter"] = tuple(d["time_filter"]) if d.get("time_filter") else None
    return EngineSettings(**kw)
