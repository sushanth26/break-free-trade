"""Day 7 — live alerts, 4:00-20:00 ET. Never places orders.

  python scripts/run_live.py                       # Webull polling, Claude on, Telegram on
  python scripts/run_live.py --dry-run --no-ai     # print alerts instead of sending, no Claude
  python scripts/run_live.py --feed alpaca         # Alpaca stand-in while Webull access is pending

History at startup = Alpaca cache + Webull CSV archive + latest Webull bars.
"""
import argparse
import asyncio
import os

import _setup  # noqa: F401

import pandas as pd

import config
from alerts.telegram import Telegram
from backtest.tuning import load_settings
from data.base import normalize_bars
from data.csv_provider import CsvProvider, write_day_csv
from data.stream import PollingSource
from live.runner import LiveRunner, rule_premarket
from live.store import Store


def load_history(symbols, live_provider):
    cache = CsvProvider(config.CACHE_DIR, cache_provider="alpaca")
    archive = CsvProvider(config.ARCHIVE_DIR)
    out = {}
    for s in symbols:
        parts = [cache.get_bars(s, "5m"), archive.get_bars(s, "5m")]
        try:
            parts.append(live_provider.get_bars(s, "5m"))
        except Exception as e:
            print(f"{s}: recent bars unavailable ({type(e).__name__})")
        bars = normalize_bars(pd.concat([p for p in parts if len(p)])) if any(len(p) for p in parts) else normalize_bars(None)
        daily = cache.get_bars(s, "D")
        out[s] = (bars, daily)
        print(f"{s:<6} {len(bars):>6} bars of history")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=list(config.BUILD_STOCKS))
    ap.add_argument("--feed", choices=["webull", "alpaca"], default="webull")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending to Telegram")
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()

    if args.feed == "webull":
        from data.webull_provider import WebullProvider
        provider = WebullProvider()
    else:
        from data.alpaca_provider import AlpacaProvider
        provider = AlpacaProvider(feed="iex")

    symbols = sorted(set(args.symbols) | set(config.REGIME_SYMBOLS))
    store = Store()
    ai = None
    if not args.no_ai and os.environ.get("ANTHROPIC_API_KEY"):
        from ai.client import AIClient
        ai = AIClient(log=store.ai_call)
    news_source = None
    if os.environ.get("ALPACA_API_KEY"):
        from data.news import fetch_alpaca_news
        news_source = lambda syms, since: fetch_alpaca_news(syms, since, pd.Timestamp.now(tz=config.TZ))
    economic = None
    try:
        from data.calendar import load_economic
        economic = load_economic()
    except Exception:
        pass

    runner = LiveRunner(symbols, load_history(symbols, provider), load_settings(), Telegram(dry_run=args.dry_run),
                        store, ai, news_source, economic)

    def archive(r, now):
        for s in symbols:
            try:
                write_day_csv(provider.get_bars(s, "5m"), s, "5m", config.ARCHIVE_DIR)
            except Exception as e:
                print(f"archive {s} failed: {type(e).__name__}")

    def premarket(r, now):
        if ai is None:
            return rule_premarket(r, now)
        from ai.replanner import allowed_levels, premarket_plan
        tickers = {}
        for s, st in r.state.items():
            if not len(st.bars):
                continue
            price = float(st.bars["close"].iloc[-1])
            zones = r._zones_info(st, now, price)
            tickers[s] = {"price": price, "zones": zones, "allowed_prices": allowed_levels(zones, 0.0, [price])}
        plan = premarket_plan(ai, tickers, [], [])
        if plan is None:
            return rule_premarket(r, now)
        return "Premarket plan\n" + "\n".join(f"{sc.ticker} [{sc.regime}] {sc.plan}" for sc in plan.scenarios)

    runner.telegram.send(f"ℹ️ Agent started · {len(symbols)} symbols · AI {'on' if ai else 'off'} · alerts only")
    asyncio.run(runner.run(PollingSource(provider, symbols), archive, premarket))


if __name__ == "__main__":
    main()
