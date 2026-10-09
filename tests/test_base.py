import pandas as pd
import pytest

from data.base import closed_bars, normalize_bars, resample, session_mask
from tests.synthetic import random_bars


def test_normalize_sorts_dedups_and_localizes():
    idx = pd.to_datetime(["2026-03-02 14:35", "2026-03-02 14:30", "2026-03-02 14:35"], utc=True)
    df = pd.DataFrame({"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
                       "Close": [1, 2, 3], "Volume": [1, 2, 3]}, index=idx)
    out = normalize_bars(df)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert str(out.index.tz) == "America/New_York"
    assert out.index.is_monotonic_increasing and out.index.is_unique
    assert out.iloc[-1]["close"] == 3.0          # duplicate keeps the last
    assert out.index[0].strftime("%H:%M") == "09:30"


def test_normalize_rejects_missing_columns():
    with pytest.raises(ValueError):
        normalize_bars(pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-03-02"], utc=True)))


def test_resample_hour_anchored_at_open():
    bars = random_bars(days=2)
    h = resample(bars, "1h")
    assert h.index[0].strftime("%H:%M") == "09:30"
    first = bars.loc[h.index[0]:h.index[0] + pd.Timedelta("55min")]
    assert h.iloc[0]["high"] == first["high"].max()
    assert h.iloc[0]["volume"] == first["volume"].sum()
    assert len(h) == 2 * 7                        # 09:30..15:30 starts


def test_resample_drops_extended_hours():
    bars = random_bars(days=1, extended=True)
    d = resample(bars, "D")
    reg = bars[session_mask(bars.index).values]
    assert d.iloc[0]["open"] == reg.iloc[0]["open"]
    assert d.iloc[0]["close"] == reg.iloc[-1]["close"]


def test_closed_bars_releases_htf_bar_only_after_close():
    h = resample(random_bars(days=1), "1h")
    t = pd.Timestamp("2026-03-02 10:25", tz="America/New_York")
    assert len(closed_bars(h, "1h", t)) == 0
    assert len(closed_bars(h, "1h", t + pd.Timedelta("5min"))) == 1
    d = resample(random_bars(days=2), "D")
    assert len(closed_bars(d, "D", pd.Timestamp("2026-03-03 15:55", tz="America/New_York"))) == 1
