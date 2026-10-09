import pandas as pd
import pytest

from engine.profile import build_profile, round_levels, round_step
from tests.synthetic import daily_from, random_bars


@pytest.mark.parametrize("price,step", [(15, 0.5), (50, 1.0), (150, 2.5), (571, 5.0)])
def test_round_step(price, step):
    assert round_step(price) == step


def test_round_levels():
    assert round_levels(571.3, 5.0, n=1) == [570.0, 575.0]
    assert round_levels(571.3, 5.0) == [565.0, 570.0, 575.0, 580.0]


def test_profile_has_no_lookahead():
    bars = random_bars(days=30)
    daily = daily_from(bars)
    as_of = bars.index[20 * 78 + 40] + pd.Timedelta("5min")
    p_full = build_profile("TEST", bars, daily, as_of)
    p_cut = build_profile("TEST", bars[bars.index < as_of], daily[daily.index < as_of.normalize()], as_of)
    assert p_full == p_cut
    assert p_full.last_price == bars.loc[bars.index < as_of, "close"].iloc[-1]
    assert p_full.atr_dist(0.5) == pytest.approx(0.5 * p_full.atr_5m)


def test_profile_needs_history():
    bars = random_bars(days=3)
    with pytest.raises(ValueError):
        build_profile("TEST", bars, daily_from(bars), bars.index[-1])
