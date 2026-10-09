import numpy as np
import pandas as pd

from engine import indicators as ind
from tests.synthetic import random_bars


def test_rma_matches_wilder_definition():
    s = pd.Series([1.0, 2, 3, 4, 5, 6])
    out = ind.rma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0                      # SMA seed
    assert out.iloc[3] == (2.0 * 2 + 4) / 3


def test_atr_ignores_overnight_gap():
    bars = random_bars(days=5, gap_pct=3.0)
    tr_gap = ind.true_range(bars)
    tr_nogap = ind.true_range(bars, ignore_gaps=True)
    day = bars.index.normalize()
    first = np.r_[False, day[1:] != day[:-1]]
    assert (tr_gap[first] > tr_nogap[first]).all()
    assert np.allclose(tr_nogap[first], (bars["high"] - bars["low"])[first])
    assert ind.atr(bars, ignore_gaps=True).iloc[-1] < ind.atr(bars).iloc[-1]


def test_vwap_resets_each_day():
    bars = random_bars(days=2)
    v = ind.vwap(bars)
    first_of_day2 = bars.index[78]
    b = bars.loc[first_of_day2]
    assert np.isclose(v.loc[first_of_day2], (b.high + b.low + b.close) / 3)


def test_ema_seeded_with_first_value():
    s = pd.Series([10.0, 11, 12])
    e = ind.ema(s, 3)
    assert e.iloc[0] == 10.0 and np.isclose(e.iloc[1], 10.5)


def test_rvol_baseline_uses_prior_days_only():
    bars = random_bars(days=3)
    base = ind.rvol_baseline(bars, lookback_days=5)
    assert base.iloc[:78].isna().all()             # day 1: no prior days
    slot0_day2 = bars.index[78]
    assert base.loc[slot0_day2] == bars["volume"].iloc[0]
    slot0_day3 = bars.index[156]
    assert base.loc[slot0_day3] == bars["volume"].iloc[[0, 78]].mean()


def test_opening_range_not_known_before_it_closes():
    bars = random_bars(days=1)
    orng = ind.opening_range(bars)
    assert orng.iloc[:2].isna().all().all()        # 09:30 and 09:35 bars
    assert orng.iloc[2]["or_high"] == bars["high"].iloc[:3].max()
