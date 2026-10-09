import pandas as pd
import pytest

from engine.break_risk import break_factors, break_risk_score, count_tests, zone_side
from engine.scoring import score_band, zone_score
from engine.strength import strength_factors, strength_score
from engine.zones import Pivot, Zone
from tests.synthetic import random_bars

ET = "America/New_York"


def _zone(bars, kinds=("high", "low"), bottom=99.8, top=100.2, tfs=("5m",)):
    t = bars.index[10]
    piv = tuple(Pivot(bars.index[5 + k], 100.0, kind, t) for k, kind in enumerate(kinds))
    return Zone(top=top, bottom=bottom, timeframes=tfs, pivots=piv, strength_raw=20 * len(piv) + 7, created_at=t)


def test_strength_factors_basic():
    bars = random_bars(days=2, seed=1)
    f = strength_factors(_zone(bars), bars, atr=0.5, round_step=1.0, prior_levels=(100.1,))
    assert f["role_flip"] == 1.0 and f["round_number"] == 1.0 and f["prior_day_level"] == 1.0
    assert f["pivots"] == 2 and f["touches"] == 7 and f["width_atr"] == pytest.approx(0.8)
    one_sided = strength_factors(_zone(bars, kinds=("high", "high")), bars, 0.5, 1.0)
    assert one_sided["role_flip"] == 0.0


def test_more_confluence_scores_higher():
    bars = random_bars(days=2, seed=1)
    weak = strength_factors(_zone(bars, kinds=("high",)), bars, 0.5, 1.0)
    strong = strength_factors(_zone(bars, tfs=("5m", "1h")), bars, 0.5, 1.0, prior_levels=(100.0,))
    assert strength_score(strong) > strength_score(weak)


def test_break_factors_and_tests_count():
    bars = random_bars(days=1, seed=2)
    z = Zone(top=bars["close"].iloc[-1] + 0.05, bottom=bars["close"].iloc[-1] - 0.05, timeframes=("5m",),
             pivots=(), strength_raw=20, created_at=bars.index[0])
    f = break_factors(z, "support", bars, atr=0.3, regime="bearish", news_against=True)
    assert f["regime_against"] == 1.0 and f["news_against"] == 1.0
    calm = dict(f, regime_against=0.0, news_against=0.0)
    assert break_risk_score(f) > break_risk_score(calm)
    assert count_tests(z, bars) >= 1
    assert zone_side(z, z.top + 1) == "support"


def test_zone_score_and_bands():
    assert zone_score(90, 5, 1.0, 1.0) == 85 and score_band(85) == "strong"
    assert zone_score(40, 60, 1.0, 1.0) == 0 and score_band(0) == "weak"
    assert score_band(60) == "medium"
