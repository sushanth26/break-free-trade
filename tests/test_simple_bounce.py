import pandas as pd

from engine.simple_bounce import ENTRY, FAIL, TOUCH, SimpleBounceTracker, plan_simple_trade
from engine.zones import Zone

ET = "America/New_York"
Z = Zone(top=100.0, bottom=99.5, timeframes=("30m",), pivots=(), strength_raw=40,
         created_at=pd.Timestamp("2026-03-02", tz=ET))


def bar(o, h, l, c, v=1000.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def run(tracker, bars, atr=1.0):
    return [tracker.step(b, atr) for b in bars]


def test_same_bar_touch_and_entry():
    t = SimpleBounceTracker(Z, "long")
    ups = run(t, [bar(100.1, 100.3, 99.6, 100.25)])
    assert ups[0].stage == ENTRY
    assert ups[0].entry_price == 100.25
    assert ups[0].stop == 99.6 - 0.1


def test_entry_after_several_bars_tracks_lowest_low():
    t = SimpleBounceTracker(Z, "long")
    ups = run(t, [bar(100.0, 100.1, 99.6, 99.8),    # touch, stays inside
                  bar(99.8, 99.9, 99.4, 99.7),       # new lower low, still inside
                  bar(99.7, 100.4, 99.9, 100.3)])    # closes back above top -> entry
    assert [u.stage for u in ups] == [TOUCH, TOUCH, ENTRY]
    assert ups[2].entry_price == 100.3
    assert ups[2].stop == 99.4 - 0.1


def test_break_cancels_setup():
    t = SimpleBounceTracker(Z, "long")
    ups = run(t, [bar(99.4, 99.5, 99.0, 99.0)])   # dips into zone, closes > 0.25 ATR below bottom
    assert ups[0].stage == FAIL and "broke zone" in ups[0].reason


def test_expires_after_bar_budget():
    t = SimpleBounceTracker(Z, "long")
    hover = bar(99.7, 99.8, 99.6, 99.7)            # inside the zone, no entry, no break
    ups = run(t, [hover] * 7)
    assert [u.stage for u in ups] == [TOUCH] * 6 + [FAIL]
    assert "bar budget" in ups[-1].reason


def test_short_is_mirror():
    t = SimpleBounceTracker(Z, "short")
    ups = run(t, [bar(99.3, 99.6, 99.2, 99.3)])   # high reaches zone bottom, closes back below it
    assert ups[0].stage == ENTRY
    assert ups[0].entry_price == 99.3
    assert ups[0].stop == 99.6 + 0.1


def test_plan_simple_trade_target_and_min_r():
    t = SimpleBounceTracker(Z, "long")
    up = run(t, [bar(100.1, 100.3, 99.6, 100.25)])[0]
    far_resistance = Zone(top=103.0, bottom=102.5, timeframes=("30m",), pivots=(), strength_raw=40,
                          created_at=Z.created_at)
    plan, why = plan_simple_trade(up, [Z, far_resistance], atr=1.0)
    assert plan is not None and why == ""
    assert plan["target"] == 102.5 - 0.1
    risk = up.entry_price - up.stop
    assert plan["r_to_target"] == (plan["target"] - up.entry_price) / risk

    near_resistance = Zone(top=100.6, bottom=100.4, timeframes=("30m",), pivots=(), strength_raw=40,
                           created_at=Z.created_at)
    plan2, why2 = plan_simple_trade(up, [Z, near_resistance], atr=1.0)
    assert plan2 is None and "R <" in why2

    plan3, why3 = plan_simple_trade(up, [Z], atr=1.0)
    assert plan3 is None and why3 == "no opposing zone"


def test_simple_bounce_has_no_lookahead():
    bars = [bar(100.0, 100.1, 99.6, 99.8), bar(99.8, 99.9, 99.4, 99.7), bar(99.7, 100.4, 99.9, 100.3)]
    t_full = SimpleBounceTracker(Z, "long")
    full = run(t_full, bars + [bar(100.3, 101.5, 100.1, 101.4)])
    t_cut = SimpleBounceTracker(Z, "long")
    cut = run(t_cut, bars)
    assert full[2] == cut[2]
