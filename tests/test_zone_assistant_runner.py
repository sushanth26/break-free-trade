import json

import pandas as pd

from alerts.telegram import Telegram
from data.base import regular_hours
from live.store import Store
from live.zone_assistant_runner import ZoneAssistantRunner, morning_sheet
from tests.synthetic import daily_from, random_bars

WEIGHTS = {
    "strength": {"bias": 0.0, "reaction_atr": 0.5, "tf_count": 0.0, "pivots": 0.3, "touches": 0.1,
                "round_number": 0.0, "prior_day_level": 0.0, "volume_ratio": 0.0, "role_flip": 0.0,
                "width_atr": -0.3, "age_bars": 0.0},
    "break": {"bias": 0.0, "recent_tests": -0.2, "approach_speed_atr": 0.1, "approach_straight": 0.1,
             "approach_rvol": 0.1, "regime_against": 0.0, "news_against": 0.0},
    "w_s": 1.0, "w_b": 0.5,
}


def _history(seed=42, days=60):
    bars = random_bars(days=days, seed=seed)
    return {"X": (bars, daily_from(bars))}


def test_runner_processes_bars_without_crash_and_links_outcomes(tmp_path):
    weights_path = tmp_path / "w.json"
    weights_path.write_text(json.dumps(WEIGHTS))
    history = _history()
    store = Store(tmp_path / "a.sqlite")
    tg = Telegram(dry_run=True)
    runner = ZoneAssistantRunner(["X"], history, tg, store, weights_path=str(weights_path))

    bars, daily = history["X"]
    reg = regular_hours(bars)
    tail = reg.iloc[-600:]
    for t, row in tail.iterrows():
        now = t + pd.Timedelta("5min")
        b = pd.DataFrame([row[["open", "high", "low", "close", "volume"]]], index=[t])
        runner.on_bars(now, {"X": b})

    alert_ids = {row[0] for row in store.db.execute("SELECT rowid FROM alerts").fetchall()}
    outcomes = store.rows("zone_outcomes")
    for row in outcomes:
        assert row[1] in alert_ids           # outcome's alert_id refers to a real alert

    kinds = [row[2] for row in store.rows("alerts")]
    # every "at zone" alert should (eventually) resolve to an outcome, or still be in flight at the run's end
    at_zone_count = sum(1 for k in kinds if k == "zone_at_zone")
    assert at_zone_count >= len(outcomes)


def test_morning_sheet_shape():
    history = _history()
    weights_path_dict = WEIGHTS
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(weights_path_dict, f)
        path = f.name
    bars, _ = history["X"]
    now = regular_hours(bars).index[-1] + pd.Timedelta("5min")
    sheet = morning_sheet(["X"], history, now, weights_path=path)
    assert "X" in sheet
    for label, zone, score, hold in sheet["X"]:
        assert isinstance(label, str) and label[0] in ("S", "R")
        assert 0.0 <= score <= 100.0
        assert 0.0 <= hold <= 1.0
