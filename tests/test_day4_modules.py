import pandas as pd
import pytest

from engine.aplus import aplus_score
from engine.bounce import CONFIRMED, FAIL, REJECTION, TOUCH, BounceTracker
from engine.events import bar_events
from engine.features import compute_features
from engine.regime import against, market_regime, regime_at, symbol_regime
from engine.zones import Zone
from tests.synthetic import daily_from, random_bars

ET = "America/New_York"
Z = Zone(top=100.0, bottom=99.5, timeframes=("5m",), pivots=(), strength_raw=40,
         created_at=pd.Timestamp("2026-03-02", tz=ET))


def bar(o, h, l, c, v=1000.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def run(tracker, bars, prev_close, atr=1.0, vol_avg=1000.0):
    out = []
    for b in bars:
        out.append(tracker.step(b, prev_close, atr, vol_avg))
        prev_close = b["close"]
    return out


def test_long_bounce_confirms():
    t = BounceTracker(Z, "long")
    ups = run(t, [bar(100.6, 100.7, 99.8, 100.15),       # touch, small wick → touch only
                  bar(100.1, 100.3, 99.6, 100.25),        # wick 0.5 of 0.7 range, close ≥ top+0.1 → rejection
                  bar(100.3, 100.9, 100.2, 100.8)], 101)  # close > 100.3, 0.65 ATR above 100.25 → confirmed
    assert [u.stage for u in ups] == [TOUCH, REJECTION, CONFIRMED]
    assert ups[1].entry_ok and ups[2].entry_ok
    assert ups[2].rej_low == 99.6
    assert ups[1].entry_price == 100.25 and ups[2].entry_price == 100.3


def test_false_bounce_fails():
    t = BounceTracker(Z, "long")
    ups = run(t, [bar(100.1, 100.3, 99.6, 100.25), bar(100.2, 100.25, 99.9, 99.95)], 101)
    assert [u.stage for u in ups] == [REJECTION, FAIL] and "false bounce" in ups[1].reason


def test_chasing_blocks_confirmed_entry():
    """Confirming bar's own close has run well past the planned entry (rej_high) -> chasing."""
    t = BounceTracker(Z, "long")
    ups = run(t, [bar(100.1, 100.3, 99.6, 100.25),     # rejection: rej_high 100.3, entry not chasing yet
                  bar(100.3, 101.0, 99.7, 100.9)], 101)  # confirms, but closes 0.6 ATR past rej_high (> 0.5 cap)
    assert ups[0].entry_ok
    assert ups[1].stage == CONFIRMED and not ups[1].entry_ok
    assert "chasing" in ups[1].reason


def test_entry_too_far_from_zone_blocks_early_entry():
    """Rejection candle itself runs 1.8 ATR above the zone -- past MAX_ENTRY_FROM_ZONE_ATR (1.5),
    even though the alert bar's own close is (trivially) not chasing its own entry."""
    t = BounceTracker(Z, "long")
    ups = run(t, [bar(101.0, 101.8, 99.6, 101.8)], 101)
    assert ups[0].stage == REJECTION and not ups[0].entry_ok
    assert "too far from zone" in ups[0].reason


def test_bounce_entry_checks_have_no_lookahead():
    """The update at bar k is identical whether or not further bars follow it."""
    bars = [bar(100.1, 100.3, 99.6, 100.25), bar(100.3, 101.0, 99.7, 100.9)]
    t_full = BounceTracker(Z, "long")
    full = run(t_full, bars + [bar(100.9, 102.5, 100.8, 102.4)], 101)
    t_cut = BounceTracker(Z, "long")
    cut = run(t_cut, bars, 101)
    assert full[1] == cut[1]


def test_short_bounce_is_mirror():
    t = BounceTracker(Z, "short")
    ups = run(t, [bar(99.35, 99.9, 99.2, 99.25), bar(99.2, 99.3, 98.6, 98.7)], 99)
    assert [u.stage for u in ups] == [REJECTION, CONFIRMED]
    assert ups[1].rej_high == 99.9 and ups[1].rej_low == 99.2
    assert ups[1].entry_price == 99.2 and ups[1].entry_ok


def test_aplus_grades():
    full = aplus_score("long", catalyst=True, confluence=True, slow_bull_5m=True, slow_bull_10m=True,
                       confirmed=True, rvol=2.0, r_to_t1=3.5, market_against=False)
    assert full.score == 7 and full.grade == "A+"
    weak = aplus_score("short", catalyst=False, confluence=False, slow_bull_5m=True, slow_bull_10m=True,
                       confirmed=True, rvol=float("nan"), r_to_t1=1.0, market_against=True)
    assert weak.score == 1 and weak.grade == "B"


def test_regime_series_known_only_after_close():
    feats = {s: compute_features(b, daily_from(b)) for s, b in
             (("SPY", random_bars(10, seed=1)), ("QQQ", random_bars(10, seed=2)), ("SMH", random_bars(10, seed=3)))}
    m = market_regime(feats)
    assert set(m["regime"]) <= {"bullish", "gap_filling", "gap_filled", "choppy", "bearish"}
    first_bar = feats["SPY"].index[0]
    assert regime_at(m, first_bar) == ("choppy", "", False)
    assert regime_at(m, first_bar + pd.Timedelta("5min"))[0] == m["regime"].iloc[0]
    assert against("bearish", "", "long") and not against("bearish", "", "short")
    assert against("gap_filling", "up", "long") and not against("gap_filling", "down", "long")
    assert len(symbol_regime(feats["SPY"])) == len(feats["SPY"])


def test_events_vwap_and_bounce():
    b = random_bars(3, seed=5)
    f = compute_features(b)
    prev, row = f.iloc[100].copy(), f.iloc[101].copy()
    prev["close"], prev["vwap"], row["close"], row["vwap"] = 10.0, 10.5, 11.0, 10.5
    t = BounceTracker(Z, "long")
    upd = t.step(bar(100.1, 100.3, 99.6, 100.25), 101, 1.0, 1000)
    ev = bar_events("X", row.name, prev, row, [upd], regime=("choppy", "bullish"))
    kinds = {e.kind for e in ev}
    assert {"vwap_reclaimed", "bounce_rejection", "regime_change"} <= kinds
    assert any(e.replan for e in ev)
