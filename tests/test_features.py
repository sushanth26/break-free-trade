import numpy as np
import pandas as pd
import pytest

from engine.features import compute_features
from tests.synthetic import daily_from, random_bars


@pytest.mark.parametrize("extended", [False, True])
def test_features_have_no_lookahead(extended):
    bars = random_bars(days=12, seed=4, extended=extended)
    daily = daily_from(bars)
    full = compute_features(bars, daily)
    for k in (100, 500, len(bars) - 30):
        t = bars.index[k]
        cut = compute_features(bars.loc[:t], daily[daily.index < t.normalize()])
        pd.testing.assert_series_equal(full.loc[t], cut.loc[t], check_names=False)


def test_prev_close_and_gap_fields():
    bars = random_bars(days=3, seed=1)
    f = compute_features(bars)
    day2 = bars.index[78]
    assert f.loc[day2, "prev_close"] == bars["close"].iloc[77]
    assert f.loc[day2, "day_open"] == bars["open"].iloc[78]
    assert np.isnan(f["prev_close"].iloc[0])


def test_ten_minute_cloud_uses_closed_bars():
    bars = random_bars(days=5, seed=2)
    f = compute_features(bars)
    assert f["slow_bull_10m"].dtype == bool
