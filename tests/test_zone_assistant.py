import pandas as pd
import pytest

from engine.zone_assistant import (APPROACHING, AT_ZONE, BROKEN, RECLAIMED, OutcomeTracker, ZoneWatchTracker,
                                   hold_rate, labelled_zones, zone_score_from_bars)
from engine.zones import Pivot, Zone
from tests.synthetic import random_bars

ET = "America/New_York"
Z = Zone(top=100.0, bottom=99.5, timeframes=("30m",), pivots=(), strength_raw=40,
         created_at=pd.Timestamp("2026-03-02", tz=ET))
WEIGHTS = {
    "strength": {"bias": 0.0, "reaction_atr": 0.5, "tf_count": 0.0, "pivots": 0.3, "touches": 0.1,
                "round_number": 0.0, "prior_day_level": 0.0, "volume_ratio": 0.0, "role_flip": 0.0,
                "width_atr": -0.3, "age_bars": 0.0},
    "break": {"bias": 0.0, "recent_tests": -0.2, "approach_speed_atr": 0.1, "approach_straight": 0.1,
             "approach_rvol": 0.1, "regime_against": 0.0, "news_against": 0.0},
    "w_s": 1.0, "w_b": 0.5,
}


def bar(o, h, l, c, v=1000.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _bars_and_row(seed=1, days=30):
    bars = random_bars(days=days, seed=seed)
    from engine.features import compute_features, feature_rows
    from tests.synthetic import daily_from
    feats = compute_features(bars, daily_from(bars))
    rows = feature_rows(feats)
    return bars, feats, rows


def test_hold_rate_bands():
    assert hold_rate(85) == 0.85
    assert hold_rate(80) == 0.85
    assert hold_rate(79.9) == 0.77
    assert hold_rate(50) == 0.77
    assert hold_rate(49.9) == 0.64


def test_zone_score_from_bars_runs_and_bounds_0_100():
    bars, feats, rows = _bars_and_row()
    i = 500
    hist, row = bars.iloc[:i + 1], rows[i]
    score = zone_score_from_bars(Z, "support", hist, row, feats["rvol"].iloc[:i + 1], WEIGHTS)
    assert 0.0 <= score <= 100.0


def test_labelled_zones_filters_by_distance_and_labels():
    bars, feats, rows = _bars_and_row()
    i = 500
    hist, row = bars.iloc[:i + 1], rows[i]
    rvol = feats["rvol"].iloc[:i + 1]
    price, atr = 100.0, 0.5
    near = Zone(top=99.9, bottom=99.7, timeframes=("30m",), pivots=(), strength_raw=40, created_at=Z.created_at)
    far = Zone(top=50.0, bottom=49.5, timeframes=("30m",), pivots=(), strength_raw=40, created_at=Z.created_at)
    out = labelled_zones([near, far], price, atr, hist, row, rvol, WEIGHTS, max_dist_atr=3.0)
    labels = {lz.label for lz in out}
    assert "S1" in labels
    assert all(lz.zone is not far for lz in out)   # far (100 ATR away) dropped


def test_approaching_then_at_zone_then_reclaim_long():
    t = ZoneWatchTracker(key=(Z.bottom, Z.top))
    atr = 1.0
    a1 = t.step("MRVL", "S1", Z, 84.0, bar(100.4, 100.5, 100.3, 100.4), prev_close=101.0, atr=atr)
    assert [u.stage for u in a1] == [APPROACHING]
    a2 = t.step("MRVL", "S1", Z, 84.0, bar(100.3, 100.4, 99.6, 99.9), prev_close=100.4, atr=atr)
    assert [u.stage for u in a2] == [AT_ZONE]
    assert t.direction == "long"
    a3 = t.step("MRVL", "S1", Z, 84.0, bar(99.9, 100.6, 99.8, 100.5), prev_close=99.9, atr=atr)
    assert [u.stage for u in a3] == [RECLAIMED]
    assert a3[0].text_args["wick"] == pytest.approx(99.6)
    assert t.stage == "idle"


def test_break_triggers_cooldown_then_resets():
    t = ZoneWatchTracker(key=(Z.bottom, Z.top))
    atr = 1.0
    t.step("MRVL", "S1", Z, 84.0, bar(100.3, 100.4, 99.6, 99.9), prev_close=101.0, atr=atr)   # at_zone
    broke = t.step("MRVL", "S1", Z, 84.0, bar(99.9, 99.9, 99.0, 99.1), prev_close=99.9, atr=atr)
    assert [u.stage for u in broke] == [BROKEN]
    assert t.stage == "cooldown"
    # no alerts while cooling down, even if price re-touches
    for _ in range(11):
        assert t.step("MRVL", "S1", Z, 84.0, bar(99.9, 100.5, 99.6, 99.9), prev_close=99.9, atr=atr) == []
    assert t.stage == "cooldown"
    # cooldown ends on this call; price is away from the zone so it lands cleanly on idle
    out = t.step("MRVL", "S1", Z, 84.0, bar(97.0, 97.1, 96.9, 97.0), prev_close=97.0, atr=atr)
    assert out == [] and t.stage == "idle"


def test_no_approaching_alert_below_min_score():
    t = ZoneWatchTracker(key=(Z.bottom, Z.top))
    out = t.step("MRVL", "S1", Z, 35.0, bar(100.4, 100.5, 100.3, 100.4), prev_close=101.0, atr=1.0)
    assert out == [] and t.stage == "idle"


def test_short_mirror():
    t = ZoneWatchTracker(key=(Z.bottom, Z.top))
    atr = 1.0
    t.step("MRVL", "R1", Z, 80.0, bar(99.3, 99.7, 99.2, 99.6), prev_close=99.0, atr=atr)   # touches from below
    assert t.direction == "short"
    out = t.step("MRVL", "R1", Z, 80.0, bar(99.6, 99.7, 99.0, 99.3), prev_close=99.6, atr=atr)
    assert [u.stage for u in out] == [RECLAIMED]


def test_outcome_tracker_held_vs_broke_vs_unresolved():
    long_t = OutcomeTracker(direction="long", zone=Z, next_zone=None)
    assert long_t.step(bar(100.0, 100.3, 99.9, 100.2), atr=1.0, hhmm="10:00") is None   # move 0.3 ATR, not yet held
    res = long_t.step(bar(100.2, 100.6, 100.1, 100.55), atr=1.0, hhmm="10:05")           # move 0.6 ATR -> held
    assert res is not None and res["outcome"] == "held"

    broke_t = OutcomeTracker(direction="long", zone=Z, next_zone=None)
    res2 = broke_t.step(bar(100.0, 100.1, 98.9, 99.0), atr=1.0, hhmm="10:00")
    assert res2["outcome"] == "broke"

    quiet_t = OutcomeTracker(direction="long", zone=Z, next_zone=None)
    assert quiet_t.step(bar(100.0, 100.1, 99.9, 100.0), atr=1.0, hhmm="15:50") is None
    res3 = quiet_t.step(bar(100.0, 100.1, 99.9, 100.0), atr=1.0, hhmm="15:55")
    assert res3 is not None and res3["outcome"] is None


def test_outcome_tracker_reaches_next_zone():
    nxt = Zone(top=102.0, bottom=101.5, timeframes=("30m",), pivots=(), strength_raw=40, created_at=Z.created_at)
    t = OutcomeTracker(direction="long", zone=Z, next_zone=nxt)
    t.step(bar(100.0, 101.6, 99.9, 101.5), atr=1.0, hhmm="10:00")
    assert t.reached_next


def test_zone_watch_tracker_has_no_lookahead():
    bars_seq = [bar(100.4, 100.5, 100.3, 100.4), bar(100.3, 100.4, 99.6, 99.9), bar(99.9, 100.6, 99.8, 100.5)]
    t_full = ZoneWatchTracker(key=(Z.bottom, Z.top))
    full = []
    pc = 101.0
    for b in bars_seq + [bar(100.5, 102.0, 100.4, 101.9)]:
        full.append(t_full.step("MRVL", "S1", Z, 84.0, b, pc, 1.0))
        pc = b["close"]
    t_cut = ZoneWatchTracker(key=(Z.bottom, Z.top))
    cut = []
    pc = 101.0
    for b in bars_seq:
        cut.append(t_cut.step("MRVL", "S1", Z, 84.0, b, pc, 1.0))
        pc = b["close"]
    assert full[: len(bars_seq)] == cut


def test_outcome_tracker_has_no_lookahead():
    bars_seq = [bar(100.0, 100.3, 99.9, 100.1), bar(100.1, 100.6, 100.0, 100.55)]
    full = OutcomeTracker(direction="long", zone=Z, next_zone=None)
    res_full = [full.step(b, 1.0, "10:0{}".format(i)) for i, b in enumerate(bars_seq + [bar(100.55, 103.0, 100.5, 102.9)])]
    cut = OutcomeTracker(direction="long", zone=Z, next_zone=None)
    res_cut = [cut.step(b, 1.0, "10:0{}".format(i)) for i, b in enumerate(bars_seq)]
    assert res_full[: len(bars_seq)] == res_cut
