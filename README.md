# Day-Trading Agent

Alert-only day-trading agent: finds strong support/resistance zones, validates
real vs false bounces, adapts bias as the market moves, and sends entry/exit
alerts to Telegram. It never places orders.

**Source of truth:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · rules for Claude Code: [CLAUDE.md](CLAUDE.md)

## Setup

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
cp .env.example .env   # fill in Webull, Alpaca, Anthropic, Telegram keys
.venv/bin/python -m pytest -q
```

## Day 1 — data + zones

```bash
python scripts/download_history.py                  # 12 months 5m + daily + news → cache/alpaca/
python scripts/check_alignment.py                   # gate: Alpaca vs Webull 5m bars must match
python scripts/run_profile.py DELL                  # StockProfile (ATR, round step)
python scripts/run_zones.py DELL --as-of "2026-10-09 11:00" --timeframes 5m 1h
python scripts/archive_webull.py                    # after the close: save Webull bars to archive/
```

Gate: zones within 0.1 ATR of TradingView ("Support Resistance Channels", same
pivot period / channel width / min strength) on 5 manually checked days.

## Status

| Layer | Module | Status |
|---|---|---|
| Config | `config.py` | ✅ |
| Data | `data/base.py`, `csv_provider.py`, `alpaca_provider.py`, `webull_provider.py`, `news.py`, `calendar.py`, `alignment.py` | ✅ built, needs live-key verification |
| Data | `stream.py` (Webull MQTT) | Day 7 |
| Engine | `indicators.py`, `profile.py` (1), `zones.py` (2) | ✅ |
| Engine | `strength.py` (3), `break_risk.py` (4) | Day 2 |
| Backtest | zone backtest, 144 configs | Day 3 |
| Engine | `regime.py` (5), `aplus.py` (6), `bounce.py` (7), `events.py` (8) | Day 4 |
| Backtest | trade backtest, fills, metrics | Day 5–6 |
| AI / Alerts / Live | Claude, Telegram, runner | Day 7 |

Open items: Webull/Alpaca/Anthropic/Telegram keys; 10 more validation stocks
(`config.VALIDATION_STOCKS`); $ risk per trade and max daily loss
(`config.RISK_PER_TRADE`, `config.MAX_DAILY_LOSS`); economic/earnings
calendars (`data/calendars/*.csv`, headers only).
