import pandas as pd

from backtest.split import walk_forward_windows
from backtest.zone_backtest import (SymbolData, apply_weights, config_grid, learn_weights, run_grid,
                                    save_weights, score_bands)
from config import ZoneConfig
from engine.scoring import load_weights
from tests.synthetic import daily_from, random_bars


def test_grid_is_144_configs():
    grid = config_grid()
    assert len(grid) == 144 and len({(c, z) for c, z in grid}) == 144


def test_small_grid_end_to_end(tmp_path):
    datas = []
    for sym, seed in (("AAA", 1), ("BBB", 2)):
        b = random_bars(days=20, seed=seed)
        datas.append(SymbolData(sym, b, daily_from(b)))
    grid = [(("5m",), ZoneConfig(pivot_period=5, channel_width_pct=3.0)),
            (("5m", "30m"), ZoneConfig(pivot_period=5, channel_width_pct=2.0))]
    touches, board = run_grid(datas, grid, min_touches=5)
    assert len(board) == 2 and board["touches"].gt(0).all()
    assert set(touches["config"]) == set(board["config"])

    weights = learn_weights(touches)
    assert set(weights) >= {"strength", "break", "w_s", "w_b"}
    scored = apply_weights(touches, weights)
    bands = score_bands(scored)
    assert list(bands.index) == ["<50", "50-79", "80+"]

    path = save_weights(weights, tmp_path / "w.json")
    assert load_weights(str(path))["source"] == str(path)


def test_walk_forward_windows():
    w = walk_forward_windows("2025-10-01", "2026-10-16")
    assert w[0][0] == pd.Timestamp("2025-10-01", tz="America/New_York")
    assert all(a[3] < b[2] for a, b in zip(w, w[1:]))      # test months do not overlap
    assert len(w) == 9
