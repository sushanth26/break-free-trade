import numpy as np
import pandas as pd

from backtest.labels import ZoneTimeline, find_touches, label_outcome
from config import ZoneConfig
from engine.features import compute_features
from engine.zones import Zone, zone_history
from tests.synthetic import random_bars

ET = "America/New_York"


def _zone(bottom=100.0, top=100.2):
    return Zone(top=top, bottom=bottom, timeframes=("5m",), pivots=(), strength_raw=40,
                created_at=pd.Timestamp("2026-03-01", tz=ET))


def test_label_hold_break_none():
    z = _zone()
    # touch bar's own high never counts as the hold (order inside the bar is unknown)
    assert label_outcome("support", z, 1.0, np.array([101.0, 100.4]), np.array([100.1, 100.15]), 0, 2)[0] == "none"
    assert label_outcome("support", z, 1.0, np.array([100.5, 100.9]), np.array([100.1, 100.3]), 0, 2)[0] == "held"
    assert label_outcome("support", z, 1.0, np.array([100.5, 100.3]), np.array([100.1, 99.4]), 0, 2)[0] == "break"
    # both in one bar → break (conservative)
    assert label_outcome("support", z, 1.0, np.array([100.5, 101.0]), np.array([100.1, 99.4]), 0, 2)[0] == "break"
    assert label_outcome("resistance", z, 1.0, np.array([100.1, 99.9]), np.array([99.9, 99.2]), 0, 2)[0] == "held"


def _timeline(bars):
    hist = zone_history(bars, "5m", ZoneConfig(pivot_period=5, channel_width_pct=3.0))
    return ZoneTimeline([t for t, _ in hist], [z for _, z in hist])


def test_touches_found_and_factors_have_no_lookahead():
    bars = random_bars(days=15, seed=9)
    feats = compute_features(bars)
    touches = find_touches(bars, feats, _timeline(bars), round_step=1.0, symbol="X")
    assert len(touches) > 20
    assert set(touches["outcome"]) <= {"held", "break", "none"}
    assert touches["strength"].between(0, 100).all() and touches["break_risk"].between(0, 100).all()

    t = touches["time"].iloc[len(touches) // 2]
    cut = bars.loc[:t]
    cut_touches = find_touches(cut, compute_features(cut), _timeline(cut), round_step=1.0, symbol="X")
    factor_cols = [c for c in touches.columns if c.startswith(("s_", "b_"))] + ["strength", "break_risk"]
    a = touches[touches["time"] == t].set_index(["bottom", "top"])[factor_cols]
    b = cut_touches[cut_touches["time"] == t].set_index(["bottom", "top"])[factor_cols]
    pd.testing.assert_frame_equal(a, b)
