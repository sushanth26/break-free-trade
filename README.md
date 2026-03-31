# Break Free Trade – Insider Filing MVP

This project now renders an **insider-trading disclosure dashboard MVP** using plain browser APIs and no framework.
It works from public CSV data (for example, SEC Form 4 exports) and runs fully offline.

## MVP features

- Daily calendar of insider filing activity (buy/sell signal per weekday).
- BUY / SELL / ALL filters.
- Filing detail panel by selected day.
- Watchlist tickers persisted in local storage.
- Alert panel for:
  - large filings (>$500K),
  - watchlist hits,
  - cluster-buying activity (2+ insiders buying same ticker in current dataset).
- CSV upload support for custom insider datasets.

## Getting started

Open `index.html` in a modern browser.

To produce a distributable build:

```bash
npm install
npm run build
```

The build script creates `dist/` with static HTML/CSS/JS.

## CSV columns supported

The parser accepts flexible headers, but these are preferred:

- `Filing Date`
- `Ticker`
- `Insider`
- `Role`
- `Transaction Type` (`BUY`/`SELL`)
- `Shares`
- `Price`
- `Value`
- `Ownership`
- `Form`

It also accepts several fallback aliases used by the prior trade journal CSV format.

## Legal note

This app is designed for **public disclosure data only** (e.g., SEC filings).
It does not ingest or encourage use of non-public material information.
