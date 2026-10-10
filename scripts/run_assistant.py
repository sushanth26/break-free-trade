"""Zone assistant -- alerts only, never places orders.

  python scripts/run_assistant.py --dry-run                        # terminal only, live polling
  python scripts/run_assistant.py --dry-run --replay 2026-10-09    # replay a past date against cached history
  python scripts/run_assistant.py                                  # live + Telegram once keys are set

Morning sheet (9:15 ET): printed, saved to reports/levels_YYYY-MM-DD.csv
and reports/levels_YYYY-MM-DD_tradingview.txt (label + price, one per line,
both zone edges -- for pasting into TradingView).
"""
import argparse
import asyncio
from pathlib import Path

import _setup  # noqa: F401

import pandas as pd

import config
from alerts.telegram import Telegram
from data.base import normalize_bars, regular_hours
from data.csv_provider import CsvProvider
from live.scheduler import next_bar_close
from live.store import Store
from live.zone_assistant_runner import ZoneAssistantRunner, morning_sheet


def load_history(symbols, provider="alpaca", end=None, use_archive=True):
    """Long history from the SIP cache + recent days from the Webull archive --
    the same source live polling uses -- so replaying a recent day sees what
    the live feed actually saw, not Alpaca's SIP data (which has its own
    recency restriction and isn't what the live system runs on anyway."""
    cache = CsvProvider(config.CACHE_DIR, cache_provider=provider)
    archive = CsvProvider(config.ARCHIVE_DIR) if use_archive else None
    out = {}
    for s in symbols:
        bars = cache.get_bars(s, "5m")
        if archive is not None:
            bars = normalize_bars(pd.concat([bars, archive.get_bars(s, "5m")]))
        daily = cache.get_bars(s, "D")
        if end is not None:
            bars, daily = bars[bars.index < end], daily[daily.index < end]
        out[s] = (bars, daily)
    return out


def print_and_save_morning_sheet(symbols, history, now, out_dir: str = "reports"):
    sheet = morning_sheet(symbols, history, now)
    rows, tv_lines = [], []
    print(f"\nMorning sheet -- {now:%Y-%m-%d} as of {now:%H:%M} ET")
    for s in symbols:
        print(f"\n{s}")
        if not sheet[s]:
            print("  no zones within range")
            continue
        print(f"  {'label':<4} {'zone':>16} {'score':>6} {'hold%':>6}")
        for label, zone, score, hold in sheet[s]:
            print(f"  {label:<4} {zone.bottom:>7.2f}-{zone.top:<7.2f} {score:>6.0f} {hold:>6.0%}")
            rows.append({"symbol": s, "label": label, "bottom": round(zone.bottom, 2), "top": round(zone.top, 2),
                        "score": round(score, 1), "hold_rate": hold})
            tv_lines += [f"{s} {label} top {zone.top:.2f}", f"{s} {label} bottom {zone.bottom:.2f}"]
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    date = now.strftime("%Y-%m-%d")
    pd.DataFrame(rows).to_csv(out / f"levels_{date}.csv", index=False)
    (out / f"levels_{date}_tradingview.txt").write_text("\n".join(tv_lines) + "\n")
    print(f"\nsaved {out}/levels_{date}.csv and {out}/levels_{date}_tradingview.txt")


def run_replay(args):
    day = pd.Timestamp(args.replay, tz=config.TZ).normalize()
    symbols = list(config.WATCHLIST)
    history = load_history(symbols, end=day)
    telegram = Telegram(dry_run=True)
    store = None if args.no_store else Store(config.DB_PATH)
    runner = ZoneAssistantRunner(symbols, history, telegram, store)

    morning_now = day + pd.Timedelta(hours=9, minutes=15)
    print_and_save_morning_sheet(symbols, history, morning_now)

    archive = CsvProvider(config.ARCHIVE_DIR)   # recent days, same source as live (Webull)
    day_bars = {}
    for s in symbols:
        b = regular_hours(archive.get_bars(s, "5m"))
        day_bars[s] = b[b.index.normalize() == day]
    times = sorted({t for s in symbols for t in day_bars[s].index})
    print(f"\nreplaying {len(times)} bars for {args.replay}...")
    for t in times:
        now = t + pd.Timedelta("5min")
        new = {s: day_bars[s].loc[[t]] for s in symbols if t in day_bars[s].index}
        runner.on_bars(now, new)
    print("replay done.")


async def _live_loop(runner, source, symbols, history):
    done_morning = False
    while True:
        now = pd.Timestamp.now(tz=config.TZ)
        if not done_morning and now.strftime("%H:%M") >= config.ZONE_ASSISTANT_MORNING_TIME:
            done_morning = True
            print_and_save_morning_sheet(symbols, history, now)
        if now.strftime("%H:%M") >= config.AFTERHOURS_END:
            break
        wake = next_bar_close(now) + pd.Timedelta(seconds=config.POLL_DELAY_S)
        await asyncio.sleep(max((wake - now).total_seconds(), 0))
        bar_close = pd.Timestamp.now(tz=config.TZ).floor("5min")
        try:
            new = await asyncio.to_thread(source.poll, bar_close)
            runner.on_bars(bar_close, new)
        except Exception as e:
            print(f"data error: {type(e).__name__}: {e}")


def run_live(args):
    symbols = list(config.WATCHLIST)
    history = load_history(symbols)
    telegram = Telegram(dry_run=args.dry_run)
    store = Store(config.DB_PATH)
    runner = ZoneAssistantRunner(symbols, history, telegram, store)

    if args.feed == "webull":
        from data.webull_provider import WebullProvider
        provider = WebullProvider()
    else:
        from data.alpaca_provider import AlpacaProvider
        provider = AlpacaProvider(feed="iex")
    from data.stream import PollingSource
    source = PollingSource(provider, symbols)

    print(f"zone assistant started -- {len(symbols)} symbols, feed={args.feed}, "
          f"telegram={'off (dry-run)' if telegram.dry_run else 'on'}")
    asyncio.run(_live_loop(runner, source, symbols, history))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending to Telegram")
    ap.add_argument("--replay", default=None, help="YYYY-MM-DD: replay a past date instead of live polling")
    ap.add_argument("--feed", choices=["webull", "alpaca"], default="webull")
    ap.add_argument("--no-store", action="store_true", help="skip SQLite logging (replay only)")
    args = ap.parse_args()
    if args.replay:
        run_replay(args)
    else:
        run_live(args)


if __name__ == "__main__":
    main()
