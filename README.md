# Day-Trading Agent

Alert-only day-trading agent: finds strong support/resistance zones, validates
real vs false bounces, adapts its bias as the market moves, and sends entry/exit
alerts to Telegram. It never places orders.

**Source of truth:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · rules for Claude Code: [CLAUDE.md](CLAUDE.md)

## Setup

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
cp .env.example .env   # Webull, Alpaca, Anthropic, Telegram keys (never commit .env)
.venv/bin/python -m pytest -q
```

## Runbook (Days 1-7)

| Day | Command | Gate |
|---|---|---|
| 1 | `python scripts/download_history.py` | 12 months 5m + daily + news cached |
| 1 | `python scripts/check_alignment.py` | Alpaca vs Webull bars match (blocks backtests) |
| 1 | `python scripts/run_zones.py NVDA --as-of "2026-10-09 11:00" --timeframes 5m 1h` | zones within 0.1 ATR of TradingView on 5 days |
| 2-3 | `python scripts/run_zone_backtest.py --jobs 8` (overnight) | score 80+ zones hold more than < 50 — **passed 2026-10-09** on `15m+1h\|p5\|w3\|s2` (edge +20.2 pts, 80+ 84% n=270 vs <50 64% n=534); `1h\|p20\|w3\|s2` (raw top hold-rate pick) was inconclusive, too few validation touches |
| 5 | `python scripts/run_trade_backtest.py tune --jobs 8` (overnight) | config chosen on train only |
| 6 | `python scripts/run_trade_backtest.py report --jobs 8` | win ≥ 60%, PF ≥ 1.5, worst-case expectancy ≥ +0.25R, adverse + neighbours pass, **chart review** of `reports/chart_review_sample.csv` |
| 7 | `python scripts/run_live.py --dry-run` then `python scripts/run_live.py` | alerts arrive on phone |
| after close | `python scripts/archive_webull.py` (also runs at 16:05 inside run_live) | Webull history builds up |

Outputs: `reports/` (leaderboards, touches, trades, robustness report),
`models/` (learned zone weights, chosen engine settings), `logs/agent.sqlite`
(every event, alert, Claude call and trade).

## Layout

| Path | What |
|---|---|
| `config.py` | every setting; distances as ATR multiples |
| `data/` | bar schema, providers (Alpaca, Webull, CSV/Parquet), news, calendars, alignment, live stream/polling |
| `engine/` | features, profile (1), zones (2), strength (3), break risk (4), regime (5), A+ (6), bounce (7), events (8), trade rules, pipeline |
| `backtest/` | touch labels, zone backtest (144 configs), fills, trade backtest, metrics, tuning, robustness report |
| `ai/` | Claude client with guardrails, news judge, re-planner, premarket planner, versioned prompts |
| `alerts/` | alert formats, Telegram sender |
| `live/` | async runner, scheduler, live zone source, SQLite store |

## Interpretations of the plan (review these)

- **Confirmed entry price.** Confirmation needs a close above the rejection high and 0.5 ATR of follow-through; the entry is the rejection candle's high (the "higher high"), worked as a limit after the alert. Early mode enters at the rejection close. Two separate distance checks guard it, after an early version conflated them and rejected most confirmed setups by construction (a rejection candle runs ~1 ATR on average, well past a 0.5 ATR cap measured from the zone edge): **chasing** (`MAX_ENTRY_DIST_ATR`, 0.5) compares the alert bar's own close to the *planned entry* — has price run away since the signal formed; **too far from zone** (`MAX_ENTRY_FROM_ZONE_ATR`, 1.5) compares the planned entry itself to the zone edge, wide enough that a normal rejection candle doesn't trip it.
- **Fills.** Entry limits fill on a touch by default; the adverse-selection rerun requires a trade-through. Targets always need a trade-through by one tick. Stops fill at the stop or the open if gapped. 0.02% slippage on every fill, commission per share.
- **Inside a bar.** Order of moves is unknown, so the stop is checked before targets, and a touch bar's own high never counts as a hold.
- **Grades.** A+ = 6-7 checks, A = 4-5, B skipped. Premarket entries need A+ (half size, limit only); A entries need a confirmed regime.
- **T1 / T2.** T1 = next opposing zone − 0.1 ATR (2R when there is none); skip if under `MIN_T1_R` or over 5R. T2 = nearer of the following zone or next round number − 0.1 ATR.
- **"Exit all on close below the 34/50 cloud"** applies after T1 (before T1 the false-bounce rule governs), so entries at support under the cloud are not closed immediately.
- **Regime.** Per symbol: gap filled / gap filling / bullish / bearish / choppy from VWAP, gap vs prior close, 10m 34/50 cloud and the opening range; market = SPY/QQQ agreement with SMH as tie-break.
- **Live data.** Polling Webull bars 2 s after each bar close is the default; the MQTT tick stream (`data/stream.py`) is wired but its message fields must be verified on the first live run.
- **News in backtests.** Catalyst = any ticker headline in the last 2 hours. News direction needs judged headlines (a `bias` column); without them news never counts as "against".

## Calendars

`data/calendars/economic.csv`: CPI and NFP (08:30 ET) and FOMC decisions
(14:00 ET), Oct 2025 – Dec 2026, including the dates moved by the 2025 and
early-2026 government shutdowns (no October 2025 CPI was published).
`data/calendars/earnings.csv`: report dates for the 12 stocks, Oct 2025 – Mar
2027, from Robinhood; all report after the close (`amc`). Dates after today
are tentative until confirmed; refresh them each quarter.

## Open items

Anthropic / Telegram keys · TradingView chart match (Day 1, zones printed,
awaiting trader comparison) and 50-trade chart review (Day 6).

Confirmed Oct 9: validation stocks stay at the current 10
(`config.VALIDATION_STOCKS`) · $ risk per trade $100 and max daily loss $300
(`config.RISK_PER_TRADE`, `config.MAX_DAILY_LOSS`).
