import pandas as pd

from backtest.report import robustness_report
from backtest.tuning import (choose, evaluate, lever_grid, load_settings, neighbours, save_settings,
                             settings_id, zone_settings_from_id)
from engine.settings import EngineSettings
from tests.test_trading import _scripted_input


def test_lever_grid_and_neighbours():
    grid = lever_grid(EngineSettings())
    assert len(grid) == 3 * 2 * 2 * 2 * 2 * 3
    s = EngineSettings(min_zone_score=65)
    nb = neighbours(s)
    assert {n.min_zone_score for n in nb if n.min_zone_score != 65} == {50, 80}
    assert all(sum(getattr(n, k) != getattr(s, k) for k in ("min_zone_score", "aplus_only", "entry_mode",
               "require_regime_agree", "time_filter", "min_t1_r")) == 1 for n in nb)


def test_settings_roundtrip(tmp_path):
    tfs, z = zone_settings_from_id("5m+1h|p10|w2|s1")
    s = EngineSettings(zone=z, timeframes=tfs, time_filter=("09:45", "15:00"), entry_mode="early")
    p = save_settings(s, tmp_path / "s.json")
    assert load_settings(p) == s and settings_id(load_settings(p)) == settings_id(s)


def test_evaluate_choose_and_report(tmp_path):
    inp, st = _scripted_input()
    res = choose(evaluate(inp, [st, st.with_(min_zone_score=99)]), min_trades=1)
    assert len(res) == 2 and res.iloc[0]["trades"] == 1
    r = robustness_report(inp, None, st, out_dir=str(tmp_path))
    assert (tmp_path / "robustness_report.md").exists()
    assert r["checks"]["chart_review"] is False
