import pandas as pd

import config
import pytest

from data.alignment import compare_bars, detect_shift, mismatches
from data.calendar import in_news_window, is_earnings_week
from data.csv_provider import CsvProvider, read_csv_bars, write_cache, write_day_csv
from data.news import headlines_before, normalize_news
from data.webull_provider import parse_bars
from engine.indicators import atr
from tests.synthetic import random_bars

ET = "America/New_York"


def test_webull_parser_tolerates_shapes():
    rows = [{"time": "2026-10-09T13:30:00Z", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100"},
            {"time": "2026-10-09T13:35:00Z", "open": "1.5", "high": "2", "low": "1", "close": "1.8", "volume": "50"}]
    a = parse_bars({"data": {"result": rows}})
    b = parse_bars([{"t": 1791552600000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100},
                    {"t": 1791552900000, "o": 1.5, "h": 2, "l": 1, "c": 1.8, "v": 50}])
    assert a.index[0] == pd.Timestamp("2026-10-09 09:30", tz=ET)
    assert a["close"].tolist() == [1.5, 1.8] and a.dtypes.eq(float).all()
    pd.testing.assert_frame_equal(a, b)
    shifted = parse_bars(rows, time_shift=-pd.Timedelta("5min"))
    assert shifted.index[0] == pd.Timestamp("2026-10-09 09:25", tz=ET)
    assert parse_bars({"data": []}).empty


def test_csv_archive_roundtrip_and_merge(tmp_path):
    bars = random_bars(days=3)
    write_day_csv(bars.iloc[:100], "dell", "5m", tmp_path)
    files = write_day_csv(bars.iloc[50:], "dell", "5m", tmp_path)
    assert len(files) == 3
    out = CsvProvider(tmp_path).get_bars("DELL", "5m")
    pd.testing.assert_frame_equal(out, bars, check_freq=False)
    one = read_csv_bars(files[0])
    assert len(one) == 78


def test_parquet_cache_and_clip(tmp_path):
    bars = random_bars(days=3)
    write_cache(bars, "alpaca", "NVDA", "5m", tmp_path)
    out = CsvProvider(tmp_path, cache_provider="alpaca").get_bars("NVDA", "5m", start="2026-03-03", end="2026-03-04")
    assert len(out) == 78 and out.index[0] == pd.Timestamp("2026-03-03 09:30", tz=ET)


def test_alignment_passes_on_identical_and_fails_on_drift():
    a = random_bars(days=5)
    assert compare_bars(a, a.copy(), "X").passed
    unit = atr(a)
    b = a.copy()
    b.iloc[100, b.columns.get_loc("close")] += 0.6 * unit.iloc[100]  # one bad print: tolerated
    r = compare_bars(a, b, "X")
    assert r.passed and r.price_outliers == 1
    for i in (150, 200):                                              # three in ~385 bars: > 0.5%
        b.iloc[i, b.columns.get_loc("close")] += 0.6 * unit.iloc[i]
    r = compare_bars(a, b, "X")
    assert not r.passed and r.price_outliers == 3


def test_alignment_tolerates_small_noise_but_not_drift():
    a = random_bars(days=5)
    unit = atr(a)
    noisy = a.copy()
    noisy.iloc[50::40, noisy.columns.get_loc("close")] += 0.2 * unit.iloc[50::40]   # ~2% of bars, 0.2 ATR
    assert compare_bars(a, noisy, "X").passed
    drift = a.copy()
    drift.iloc[20:, drift.columns.get_loc("close")] += 0.15 * unit.iloc[20:]       # every bar 0.15 ATR off
    assert not compare_bars(a, drift, "X").passed


def test_alignment_volume_skips_auction_bar_only():
    a = random_bars(days=5)
    auction = a.index.strftime("%H:%M") == "15:55"
    b = a.copy()
    b.loc[auction, "volume"] *= 3                          # Webull folds the closing cross in
    b.loc[auction, "close"] += 1.0                         # including its price
    assert compare_bars(a, b, "X").passed
    b = a.copy()
    b.iloc[::10, b.columns.get_loc("volume")] *= 1.5       # 10% of ordinary bars off
    assert not compare_bars(a, b, "X").passed


def test_alignment_skips_forming_day_and_lists_mismatches():
    a = random_bars(days=5)
    b = a.copy()
    b.iloc[100, b.columns.get_loc("close")] += 0.3 * atr(a).iloc[100]
    b = b.iloc[:-3]                                        # last day still forming on one side
    last = a.index[-1].normalize()
    assert compare_bars(a, b, "X").only_a == 3
    r = compare_bars(a, b, "X", before=last)
    assert r.only_a == 0 and r.only_b == 0 and r.price_fail == 1 and r.passed
    bad = mismatches(a, b, before=last)
    assert list(bad.index) == [a.index[100]] and abs(bad["close_atr"].iloc[0] - 0.3) < 1e-9


def test_alignment_detects_bar_end_timestamps():
    a = random_bars(days=5)
    b = a.set_axis(a.index + pd.Timedelta("5min"))        # stamped with bar end
    assert detect_shift(a, b) == 1
    assert not compare_bars(a, b, "X").passed


def test_news_only_before_bar_close():
    news = normalize_news([
        {"id": 1, "created_at": "2026-10-09T14:00:00Z", "headline": "a", "symbols": ["DELL"]},
        {"id": 2, "created_at": "2026-10-09T14:05:00Z", "headline": "b", "symbols": ["NVDA"]},
    ])
    t = pd.Timestamp("2026-10-09 10:05", tz=ET)               # = 14:05Z
    assert headlines_before(news, t)["id"].tolist() == [1]
    assert headlines_before(news, t + pd.Timedelta("1s"), symbols={"NVDA"})["id"].tolist() == [2]


def test_news_window_and_earnings_week():
    econ = pd.DataFrame({"time": [pd.Timestamp("2026-10-14 08:30", tz=ET)], "event": ["CPI"]})
    assert in_news_window("2026-10-14 08:25", econ)
    assert in_news_window("2026-10-14 08:45", econ)
    assert not in_news_window("2026-10-14 08:46", econ)
    earn = pd.DataFrame({"date": [pd.Timestamp("2026-10-28").date()], "symbol": ["META"]})
    assert is_earnings_week("meta", "2026-10-26 10:00", earn)
    assert not is_earnings_week("META", "2026-10-19 10:00", earn)


def test_news_fetch_passes_no_total_limit(monkeypatch):
    """alpaca-py treats ``limit`` as a total cap; passing one truncated a year of news to 50."""
    import types, sys
    seen = {}

    class FakeReq:
        def __init__(self, **kw):
            seen.update(kw)

    class FakeClient:
        def __init__(self, *a):
            pass

        def get_news(self, req):
            return types.SimpleNamespace(data={"news": [
                {"id": i, "created_at": "2026-10-09T14:00:00Z", "headline": "h", "symbols": ["DELL"]}
                for i in range(120)]})

    monkeypatch.setitem(sys.modules, "alpaca.data.historical.news", types.SimpleNamespace(NewsClient=FakeClient))
    monkeypatch.setitem(sys.modules, "alpaca.data.requests", types.SimpleNamespace(NewsRequest=FakeReq))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    from data.news import fetch_alpaca_news
    out = fetch_alpaca_news(["DELL"], "2026-01-01", "2026-10-09")
    assert "limit" not in seen and len(out) == 120
