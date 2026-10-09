import numpy as np
import pandas as pd
import pytest

from config import ZoneConfig
from data.base import resample
from engine.zones import (Zone, compute_zones, find_pivots, label_zones, merge_zones,
                          multi_timeframe_zones, zone_history, zones_at)
from tests.synthetic import random_bars, session_index

CFG = ZoneConfig(pivot_period=5, channel_width_pct=3.0, min_strength=1)


def bars_from_highs_lows(highs, lows):
    idx = session_index(1)[:len(highs)]
    h, l = np.array(highs, float), np.array(lows, float)
    mid = (h + l) / 2
    return pd.DataFrame({"open": mid, "high": h, "low": l, "close": mid, "volume": 1000.0}, index=idx)


def test_pivot_confirmed_period_bars_later():
    highs = [10, 11, 12, 15, 12, 11, 10, 10, 10]
    lows = [h - 1 for h in highs]
    bars = bars_from_highs_lows(highs, lows)
    piv = find_pivots(bars, 3, "5m")
    ph = [p for p in piv if p.kind == "high"]
    assert len(ph) == 1 and ph[0].price == 15
    assert ph[0].time == bars.index[3]
    assert ph[0].confirmed_at == bars.index[6] + pd.Timedelta("5min")


def test_equal_highs_pivot_goes_to_earlier_bar():
    highs = [10, 11, 15, 15, 11, 10, 10]
    piv = find_pivots(bars_from_highs_lows(highs, [h - 1 for h in highs]), 2, "5m")
    assert [p.time for p in piv if p.kind == "high"] == [session_index(1)[2]]


def test_nearby_pivots_form_one_zone():
    # three swing highs at ~100.0-100.2 separated by dips to 98
    pattern = [98, 98.5, 99, 99.5, 100.0, 99.5, 99, 98.5, 98, 98.5, 99, 99.5, 100.2, 99.5,
               99, 98.5, 98, 98.5, 99, 99.5, 100.1, 99.5, 99, 98.5, 98, 98, 98, 98]
    bars = bars_from_highs_lows(pattern, [p - 0.3 for p in pattern])
    cfg = ZoneConfig(pivot_period=3, channel_width_pct=10.0, min_strength=2, max_zones=3)
    zones = compute_zones(bars, "5m", bars.index[-1] + pd.Timedelta("5min"), cfg)
    top = max(zones, key=lambda z: z.top)
    assert top.top == pytest.approx(100.2) and top.bottom == pytest.approx(100.0)
    assert len([p for p in top.pivots if p.kind == "high"]) == 3
    assert top.strength_raw >= 60


def test_zone_widths_respect_channel_width():
    bars = random_bars(days=10, seed=3)
    for t, zones in zone_history(bars, "5m", CFG):
        cur = bars[bars.index + pd.Timedelta("5min") <= t].iloc[-CFG.range_bars:]
        cwidth = (cur["high"].max() - cur["low"].min()) * CFG.channel_width_pct / 100
        assert all(z.width <= cwidth + 1e-9 for z in zones)
        assert len(zones) <= CFG.max_zones
        assert all(not a.overlaps(b) for i, a in enumerate(zones) for b in zones[i + 1:])


@pytest.mark.parametrize("tf", ["5m", "15m", "1h"])
def test_zones_have_no_lookahead(tf):
    bars5 = random_bars(days=25, seed=7)
    bars = bars5 if tf == "5m" else resample(bars5, tf)
    for k in (300, 777, 1234, 1800):
        now = bars5.index[k] + pd.Timedelta("5min")
        full = compute_zones(bars, tf, now, CFG)
        cut = compute_zones(bars[bars.index < now], tf, now, CFG)
        assert full == cut
        assert all(z.created_at <= now for z in full)
        assert all(p.confirmed_at <= now for z in full for p in z.pivots)


def test_multi_timeframe_zones_have_no_lookahead():
    bars5 = random_bars(days=25, seed=11)
    now = bars5.index[1500] + pd.Timedelta("5min")
    tfs = ("5m", "30m", "1h")
    full = multi_timeframe_zones(bars5, tfs, now, CFG)
    cut = multi_timeframe_zones(bars5[bars5.index < now], tfs, now, CFG)
    assert full == cut and len(full) > 0


def test_higher_timeframe_zone_waits_for_bar_close_and_confirmation():
    bars5 = random_bars(days=25, seed=5)
    h = resample(bars5, "1h")
    for t, zones in zone_history(h, "1h", CFG):
        for z in zones:
            for p in z.pivots:
                # pivot bar + period more 1h bars must have closed
                assert p.confirmed_at >= p.time + pd.Timedelta(hours=CFG.pivot_period + 1)
            assert z.created_at == t
    hist = zone_history(h, "1h", CFG)
    first_t = hist[0][0]
    assert zones_at(hist, first_t - pd.Timedelta("1s")) == []


def _z(bottom, top, tf, strength=40):
    t = pd.Timestamp("2026-03-02 10:00", tz="America/New_York")
    return Zone(top=top, bottom=bottom, timeframes=(tf,), pivots=(), strength_raw=strength, created_at=t)


def test_merge_overlapping_zones_across_timeframes():
    merged = merge_zones([_z(99, 100, "5m"), _z(99.5, 100.5, "1h"), _z(90, 91, "5m")])
    assert len(merged) == 2
    m = [z for z in merged if z.top > 95][0]
    assert (m.bottom, m.top, m.timeframes, m.strength_raw) == (99, 100.5, ("5m", "1h"), 80)


def test_labels_nearest_first():
    zones = [_z(90, 91, "5m"), _z(95, 96, "5m"), _z(101, 102, "5m"), _z(110, 111, "5m")]
    labels = {name: (z.bottom, z.top) for name, z in label_zones(zones, 98.0)}
    assert labels == {"S1": (95, 96), "S2": (90, 91), "R1": (101, 102), "R2": (110, 111)}
