import pandas as pd
import pytest

from backtest.fills import FillModel
from backtest.simple_bounce_backtest import (by_band, by_direction, by_symbol, mfe_diagnostic, mfe_summary,
                                             save_chart_review, simulate, summarize)
from backtest.zone_backtest import SymbolData
from tests.synthetic import daily_from, random_bars


def _symbol_data(days, seed):
    bars = random_bars(days=days, seed=seed)
    return SymbolData(f"SIM{seed}", bars, daily_from(bars))


WEIGHTS = {
    "strength": {"bias": 0.0, "reaction_atr": 0.5, "tf_count": 0.0, "pivots": 0.3, "touches": 0.1,
                "round_number": 0.0, "prior_day_level": 0.0, "volume_ratio": 0.0, "role_flip": 0.0,
                "width_atr": -0.3, "age_bars": 0.0},
    "break": {"bias": 0.0, "recent_tests": -0.2, "approach_speed_atr": 0.1, "approach_straight": 0.1,
             "approach_rvol": 0.1, "regime_against": 0.0, "news_against": 0.0},
    "w_s": 1.0, "w_b": 0.5,
}


def test_summarize_and_groupers():
    trades = pd.DataFrame([
        {"symbol": "A", "direction": "long", "win": True, "r": 2.0, "score": 85},
        {"symbol": "A", "direction": "long", "win": False, "r": -1.0, "score": 40},
        {"symbol": "B", "direction": "short", "win": True, "r": 1.5, "score": 60},
    ])
    s = summarize(trades)
    assert s["trades"] == 3
    assert s["win_rate"] == pytest.approx(2 / 3)
    assert s["profit_factor"] == pytest.approx((2.0 + 1.5) / 1.0)
    assert s["expectancy_r"] == pytest.approx((2.0 - 1.0 + 1.5) / 3)

    bands = by_band(trades).set_index("band")
    assert bands.loc["80+", "trades"] == 1 and bands.loc["<50", "trades"] == 1
    assert by_direction(trades).set_index("direction").loc["long", "trades"] == 2
    assert by_symbol(trades).set_index("symbol").loc["B", "trades"] == 1


def test_save_chart_review(tmp_path):
    trades = pd.DataFrame([
        {"symbol": "A", "direction": "long", "entry_time": pd.Timestamp(f"2026-01-0{i}", tz="America/New_York"),
         "zone_bottom": 99.0, "zone_top": 99.5,
         "entry": 100.0, "stop": 99.0, "target": 102.0, "exit_time": pd.Timestamp(f"2026-01-0{i}", tz="America/New_York"),
         "exit_reason": "target hit", "r": 2.0, "score": 70} for i in range(1, 6)
    ])
    out = save_chart_review(trades, str(tmp_path / "review.csv"), n=3, seed=1)
    assert len(out) == 3
    assert (tmp_path / "review.csv").exists()


def test_simulate_has_no_lookahead():
    datas = {d.symbol: d for d in (_symbol_data(70, 1), _symbol_data(70, 2))}
    start = datas[next(iter(datas))].bars.index[0]
    cutoff = datas[next(iter(datas))].bars.index[int(len(datas[next(iter(datas))].bars) * 0.6)]

    full_trades, full_skipped = simulate(datas, WEIGHTS, start, cutoff.normalize(), FillModel())

    truncated = {s: SymbolData(s, d.bars[d.bars.index <= cutoff], d.daily) for s, d in datas.items()}
    cut_trades, cut_skipped = simulate(truncated, WEIGHTS, start, cutoff.normalize(), FillModel())

    pd.testing.assert_frame_equal(full_trades.reset_index(drop=True), cut_trades.reset_index(drop=True))


def test_simulate_adverse_selection_matches_base_run():
    """Entries are a direct fill at the signal bar's own close (not a resting limit
    order), so the adverse-selection rerun cannot differ from the base run."""
    datas = {d.symbol: d for d in (_symbol_data(70, 3),)}
    start = next(iter(datas.values())).bars.index[0].normalize()
    end = next(iter(datas.values())).bars.index[-1].normalize()
    base, _ = simulate(datas, WEIGHTS, start, end, FillModel())
    adverse, _ = simulate(datas, WEIGHTS, start, end, FillModel(adverse_selection=True))
    pd.testing.assert_frame_equal(base.reset_index(drop=True), adverse.reset_index(drop=True))


def test_mfe_diagnostic_stops_counting_on_the_stop_bar():
    ET = "America/New_York"
    idx = pd.date_range("2026-01-05 09:30", "2026-01-05 15:55", freq="5min", tz=ET)
    bars = pd.DataFrame({"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 1000.0}, index=idx)
    entry_time = idx[0]
    bars.loc[idx[1], ["high", "low", "close"]] = [100.6, 100.3, 100.5]     # +0.6R
    bars.loc[idx[2], ["high", "low", "close"]] = [101.2, 100.8, 101.1]    # +1.2R
    bars.loc[idx[3], ["high", "low", "close"]] = [101.5, 98.5, 99.0]      # stop (99.0) hit -- doesn't count the 1.5R high
    d = SymbolData("X", bars, daily_from(bars))

    trades = pd.DataFrame([{"symbol": "X", "direction": "long", "entry_time": entry_time,
                           "entry": 100.0, "stop": 99.0, "score": 70}])
    mfe = mfe_diagnostic(trades, {"X": d})
    assert mfe.loc[0, "mfe_r"] == pytest.approx(1.2)
    assert bool(mfe.loc[0, "stopped"])
    assert mfe.loc[0, "reached_1R"] and not mfe.loc[0, "reached_1.5R"]

    summ = mfe_summary(mfe).set_index("threshold")
    assert summ.loc["1R", "share_reached"] == 1.0
    assert summ.loc["1.5R", "share_reached"] == 0.0
