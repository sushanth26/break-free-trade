# CLAUDE.md — Day-Trading Agent

Read docs/ARCHITECTURE.md before any change. It is the source of truth.

## Rules
- Python 3.12. Pure functions in engine/; no I/O inside engine modules.
- Every distance = multiple of 5m ATR from StockProfile. Never hardcode dollars.
- No lookahead: a value at bar t uses only bars <= t. Add a lookahead test for every new module.
- Same engine code for backtest and live. No backtest-only shortcuts.
- Limit fills only when price trades through. Slippage 0.02% of price. Commission from config. Adverse-selection rerun must pass.
- Alerts only. Never call any order-placing API.
- Secrets from .env only. Never print or commit keys.
- Run `python -m pytest -q` after every change; all tests must pass before moving on.
- Keep config in config.py; no magic numbers in modules.
- Commit at the end of each working step with a clear message.

## Build order
Day 1 data download + zones · Day 2 strength + break risk + labels · Day 3 zone backtest (144 configs) + weights · Day 4 regime, A+, bounce, events · Day 5 trade backtest + tuning (train only) · Day 6 out-of-sample + robustness report (pass: win >= 60%, PF >= 1.5, expectancy >= +0.25R worst case, trader chart review) · Day 7 live runner + Claude + Telegram.

## Conventions in this repo
- Bar schema: pandas DataFrame, tz-aware index in America/New_York, columns open/high/low/close/volume (float), sorted, de-duplicated. Index = bar START time. Use `data.base.normalize_bars` on every provider output.
- A bar is usable at `start + timeframe` (its close). `data.base.closed_bars` enforces this for higher timeframes.
- Tests live in tests/; synthetic bar generators in tests/synthetic.py.

## Trader preferences
- Chart levels: short labels (S1, R1), exact prices, few levels, black lines, no HOD/LOD/pivot lines.
- Reports and alerts: short, tables, exact prices.
