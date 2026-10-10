import pytest

import config
from live import dashboard_api as api
from live.store import Store


def test_get_alerts_filters_by_symbol_and_since(tmp_path):
    store = Store(tmp_path / "a.sqlite")
    store.alert("MRVL", "zone_at_zone", "at S1", True, time="2026-10-09 10:00:00", score=84.0)
    store.alert("DELL", "zone_approaching", "approaching R1", True, time="2026-10-09 11:00:00", score=60.0)

    all_alerts = api.get_alerts(store)
    assert len(all_alerts) == 2
    mrvl_only = api.get_alerts(store, symbol="MRVL")
    assert len(mrvl_only) == 1 and mrvl_only[0]["symbol"] == "MRVL"
    since = api.get_alerts(store, since="2026-10-09 10:30:00")
    assert len(since) == 1 and since[0]["symbol"] == "DELL"


def test_journal_add_close_and_report(tmp_path):
    store = Store(tmp_path / "a.sqlite")
    alert_id = store.alert("MRVL", "zone_at_zone", "at S1", True, score=84.0)

    added = api.add_journal(store, {"symbol": "mrvl", "direction": "long", "entry": "100", "stop": "99",
                                    "target": "103", "alert_id": alert_id, "note": "test"})
    rows = api.get_journal(store)
    assert rows[0]["symbol"] == "MRVL" and rows[0]["alert_id"] == alert_id and rows[0]["alert_score"] == 84.0

    closed = api.close_journal(store, added["id"], {"exit": "101.5"})
    assert closed["r"] == pytest.approx(1.5)


def test_add_journal_requires_fields(tmp_path):
    store = Store(tmp_path / "a.sqlite")
    with pytest.raises(ValueError):
        api.add_journal(store, {"symbol": "MRVL", "direction": "long"})


def test_watchlist_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_PATH", str(tmp_path / "w.json"))
    assert api.get_watchlist() == list(config.WATCHLIST)   # no file yet -> seed default
    out = api.set_watchlist({"symbols": ["nvda", "amd", "nvda"]})
    assert out == ["NVDA", "AMD", "NVDA"]
    assert api.get_watchlist() == ["NVDA", "AMD", "NVDA"]


def test_set_watchlist_rejects_bad_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_PATH", str(tmp_path / "w.json"))
    with pytest.raises(ValueError):
        api.set_watchlist({"symbols": "NVDA"})


def test_get_summary_shape(tmp_path):
    store = Store(tmp_path / "a.sqlite")
    store.alert("MRVL", "zone_at_zone", "at S1", True, score=84.0)
    s = api.get_summary(store)
    assert s["alerts"] == 1 and s["journal_trades"] == 0 and "watchlist" in s
