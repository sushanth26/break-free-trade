# Break Free Trade

This project renders a static snapshot of a trading journal using plain browser APIs. The interface is
styled with modern CSS and rendered without a framework so it can run entirely offline.

## Getting started

No build tools or package downloads are required to view the project. Simply open `index.html` in a
modern browser.

If you want a distributable copy, run:

```bash
npm install
npm run build
```

The build script creates a ready-to-serve `dist/` directory containing the HTML, CSS, and JavaScript
modules.

## Project structure

- `src/index.css` – global styles for the dashboard UI.
- `src/main.js` – bootstraps the page and renders the dashboard markup.
- `src/data/calendar.js` – static data set describing daily trading results.
- `src/utils/format.js` – helper utilities for currency, percentages, and sentiment classes.
