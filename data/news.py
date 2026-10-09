"""Headlines with publish timestamps (Alpaca / Benzinga), historical and live.

Standard news frame: columns id, published_at (tz-aware, America/New_York),
headline, symbols (tuple), source; sorted by published_at.
"""
from __future__ import annotations

import os

import pandas as pd

import config
from data.base import to_ts

NEWS_COLUMNS = ["id", "published_at", "headline", "symbols", "source"]


def normalize_news(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=NEWS_COLUMNS)
    df = pd.DataFrame([{
        "id": r.get("id"),
        "published_at": r.get("created_at") or r.get("published_at"),
        "headline": r.get("headline", ""),
        "symbols": tuple(r.get("symbols") or ()),
        "source": r.get("source", ""),
    } for r in rows])
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True).dt.tz_convert(config.TZ)
    return df.drop_duplicates("id").sort_values("published_at").reset_index(drop=True)


def headlines_before(news: pd.DataFrame, t: pd.Timestamp, symbols: set[str] | None = None,
                     since: pd.Timestamp | None = None) -> pd.DataFrame:
    """Headlines published strictly before ``t`` (a bar close), optionally filtered."""
    out = news[news["published_at"] < to_ts(t)]
    if since is not None:
        out = out[out["published_at"] >= to_ts(since)]
    if symbols:
        out = out[out["symbols"].apply(lambda s: bool(set(s) & symbols))]
    return out


def fetch_alpaca_news(symbols: list[str], start, end, page_limit: int = 50) -> pd.DataFrame:
    """Download headlines for ``symbols`` between start and end (pages through results)."""
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest

    client = NewsClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
    rows: list[dict] = []
    token = None
    while True:
        req = NewsRequest(symbols=",".join(symbols), start=to_ts(start).to_pydatetime(),
                          end=to_ts(end).to_pydatetime(), limit=page_limit,
                          include_content=False, page_token=token)
        res = client.get_news(req)
        items = res.data.get("news", []) if hasattr(res, "data") else []
        rows += [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in items]
        token = getattr(res, "next_page_token", None)
        if not token:
            break
    return normalize_news(rows)
