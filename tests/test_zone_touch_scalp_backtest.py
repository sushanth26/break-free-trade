import pandas as pd

from backtest.fills import FillModel
from backtest.zone_backtest import SymbolData
from backtest.zone_touch_scalp_backtest import simulate
from tests.synthetic import daily_from, random_bars

WEIGHTS = {
    "strength": {"bias": 0.0, "reaction_atr": 0.5, "tf_count": 0.0, "pivots": 0.3, "touches": 0.1,
                "round_number": 0.0, "prior_day_level": 0.0, "volume_ratio": 0.0, "role_flip": 0.0,
                "width_atr": -0.3, "age_bars": 0.0},
    "break": {"bias": 0.0, "recent_tests": -0.2, "approach_speed_atr": 0.1, "approach_straight": 0.1,
             "approach_rvol": 0.1, "regime_against": 0.0, "news_against": 0.0},
    "w_s": 1.0, "w_b": 0.5,
}


def _symbol_data(days, seed):
    bars = random_bars(days=days, seed=seed)
    return SymbolData(f"SIM{seed}", bars, daily_from(bars))


def test_schema_and_no_crash_low_min_score():
    datas = {d.symbol: d for d in (_symbol_data(80, 11), _symbol_data(80, 12))}
    start = next(iter(datas.values())).bars.index[0].normalize()
    end = next(iter(datas.values())).bars.index[-1].normalize()
    trades, skipped = simulate(datas, WEIGHTS, start, end, min_score=0.0)
    for col in ("symbol", "direction", "entry", "stop", "target", "zone_bottom", "zone_top", "score", "r"):
        assert col in trades.columns
    if len(trades):
        # entry = zone edge +/- slippage (and the bar's open instead, if it gapped past the limit)
        longs = trades[trades["direction"] == "long"]
        assert ((longs["entry"] - longs["zone_top"]).abs() < 0.05 * longs["zone_top"]).all() or longs.empty
        assert (longs["target"] > longs["entry"]).all()
        assert (longs["stop"] < longs["entry"]).all()
        shorts = trades[trades["direction"] == "short"]
        assert ((shorts["entry"] - shorts["zone_bottom"]).abs() < 0.05 * shorts["zone_bottom"]).all() or shorts.empty
        assert (shorts["target"] < shorts["entry"]).all()
        assert (shorts["stop"] > shorts["entry"]).all()


def test_min_score_80_is_a_subset_of_min_score_0():
    datas = {d.symbol: d for d in (_symbol_data(80, 21),)}
    start = next(iter(datas.values())).bars.index[0].normalize()
    end = next(iter(datas.values())).bars.index[-1].normalize()
    loose, _ = simulate(datas, WEIGHTS, start, end, min_score=0.0)
    strict, _ = simulate(datas, WEIGHTS, start, end, min_score=80.0)
    assert len(strict) <= len(loose)
    if len(strict):
        assert (strict["score"] >= 80.0).all()


def test_zone_touch_scalp_has_no_lookahead():
    """Results through a cutoff DAY must not depend on data after it. The cutoff must be a
    whole-day boundary: simulate()'s ``end`` processes the entire calendar day, so trimming
    bars at an arbitrary mid-day point (rather than after that day's last bar) would make the
    truncated run missing real bars for its own last day -- a test artifact, not a lookahead leak."""
    datas = {d.symbol: d for d in (_symbol_data(70, 31), _symbol_data(70, 32))}
    one = next(iter(datas.values()))
    all_days = sorted(set(one.bars.index.normalize()))
    cutoff_day = all_days[int(len(all_days) * 0.6)]
    start = one.bars.index[0]

    full_trades, _ = simulate(datas, WEIGHTS, start, cutoff_day, FillModel(adverse_selection=True), min_score=0.0)
    truncated = {s: SymbolData(s, d.bars[d.bars.index.normalize() <= cutoff_day], d.daily) for s, d in datas.items()}
    cut_trades, _ = simulate(truncated, WEIGHTS, start, cutoff_day, FillModel(adverse_selection=True), min_score=0.0)
    pd.testing.assert_frame_equal(full_trades.reset_index(drop=True), cut_trades.reset_index(drop=True))
