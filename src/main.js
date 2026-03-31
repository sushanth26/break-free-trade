import { formatCurrency, formatPercent, pluralize, sentimentClass } from './utils/format.js';

let appRoot = null;

const WATCHLIST_STORAGE_KEY = 'insider-watchlist';

const parseCsvLine = (line) => {
  const result = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];

    if (char === '"') {
      if (inQuotes && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === ',' && !inQuotes) {
      result.push(current.trim());
      current = '';
      continue;
    }

    current += char;
  }

  result.push(current.trim());
  return result;
};

const parseCsv = (text) => {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  if (lines.length === 0) {
    return [];
  }

  const headers = parseCsvLine(lines[0]);
  const records = [];

  for (let index = 1; index < lines.length; index += 1) {
    const rawValues = parseCsvLine(lines[index]);
    const record = {};

    headers.forEach((header, headerIndex) => {
      const value = rawValues[headerIndex] ?? '';
      record[header] = value;
    });

    records.push(record);
  }

  return records;
};

const createEl = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (typeof text === 'string') {
    element.textContent = text;
  }
  return element;
};

const parseDate = (value) => {
  if (!value) {
    return null;
  }

  const parts = value.split(/[-/]/);
  if (parts.length !== 3) {
    return null;
  }

  if (value.includes('-')) {
    const [yearPart, monthPart, dayPart] = parts;
    const year = Number.parseInt(yearPart, 10);
    const month = Number.parseInt(monthPart, 10) - 1;
    const day = Number.parseInt(dayPart, 10);
    return Number.isFinite(year) && Number.isFinite(month) && Number.isFinite(day)
      ? new Date(year, month, day)
      : null;
  }

  const [monthPart, dayPart, yearPart] = parts;
  const month = Number.parseInt(monthPart, 10) - 1;
  const day = Number.parseInt(dayPart, 10);
  const year = Number.parseInt(yearPart.length === 2 ? `20${yearPart}` : yearPart, 10);

  if (!Number.isFinite(month) || !Number.isFinite(day) || !Number.isFinite(year)) {
    return null;
  }

  return new Date(year, month, day);
};

const parseNumber = (value) => {
  if (!value) {
    return 0;
  }

  const cleaned = value.replace(/[$,%]/g, '').trim();
  const negative = cleaned.startsWith('(') && cleaned.endsWith(')');
  const numeric = Number.parseFloat(cleaned.replace(/[()]/g, ''));

  if (!Number.isFinite(numeric)) {
    return 0;
  }

  return negative ? -numeric : numeric;
};

const getRecordField = (record, options) => {
  for (let index = 0; index < options.length; index += 1) {
    const key = options[index];
    if (record[key] !== undefined && record[key] !== '') {
      return record[key];
    }
  }
  return '';
};

const normalizeInsiderRecords = (records) =>
  records
    .map((record) => {
      const filingDateRaw = getRecordField(record, ['Filing Date', 'Date', 'Activity Date']);
      const filingDate = parseDate(filingDateRaw);
      const value = parseNumber(getRecordField(record, ['Value', 'Amount', 'Transaction Value']));
      const shares = parseNumber(getRecordField(record, ['Shares', 'Quantity']));
      const transactionType = getRecordField(record, ['Transaction Type', 'Action', 'Trans Code']).toUpperCase();
      const ticker = getRecordField(record, ['Ticker', 'Instrument', 'Symbol']).toUpperCase();
      const insider = getRecordField(record, ['Insider', 'Insider Name', 'Name']) || 'Unknown insider';
      const role = getRecordField(record, ['Role', 'Relationship', 'Title']) || 'Not specified';
      const form = getRecordField(record, ['Form', 'Form Type']) || 'Form 4';
      const ownership = getRecordField(record, ['Ownership', 'Ownership Type']) || 'Direct';

      if (!filingDate || !ticker) {
        return null;
      }

      const isBuy = transactionType.includes('BUY') || transactionType === 'A';
      const isSell = transactionType.includes('SELL') || transactionType === 'D';
      const signedValue = isSell ? -Math.abs(value) : Math.abs(value);

      return {
        filingDate,
        filingDateRaw,
        ticker,
        insider,
        role,
        transactionType,
        shares,
        value: Math.abs(value),
        signedValue,
        ownership,
        form,
        isBuy,
        isSell,
      };
    })
    .filter(Boolean);

const formatIsoKey = (year, month, day) =>
  `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

const buildCalendarData = (records, filterMode) => {
  const filtered =
    filterMode === 'all' ? records : records.filter((record) => (filterMode === 'buy' ? record.isBuy : record.isSell));

  if (filtered.length === 0) {
    throw new Error('No records found for selected filter.');
  }

  const dates = filtered.map((record) => record.filingDate).sort((a, b) => a - b);
  const month = dates[0].getMonth();
  const year = dates[0].getFullYear();

  const dailyMap = new Map();
  filtered.forEach((record) => {
    if (record.filingDate.getMonth() !== month || record.filingDate.getFullYear() !== year) {
      return;
    }

    const day = record.filingDate.getDate();
    const key = formatIsoKey(year, month, day);
    const aggregate = dailyMap.get(key) ?? {
      date: day,
      signal: 0,
      filings: 0,
      buys: 0,
      sells: 0,
      records: [],
    };

    aggregate.signal += record.signedValue;
    aggregate.filings += 1;
    if (record.isBuy) {
      aggregate.buys += 1;
    }
    if (record.isSell) {
      aggregate.sells += 1;
    }
    aggregate.records.push(record);
    dailyMap.set(key, aggregate);
  });

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const weeks = [];
  let currentWeek = new Array(5).fill(null);
  let weekIndex = 0;

  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = new Date(year, month, day);
    const dayOfWeek = date.getDay();

    if (dayOfWeek === 0 || dayOfWeek === 6) {
      continue;
    }

    const key = formatIsoKey(year, month, day);
    const aggregate = dailyMap.get(key);

    currentWeek[weekIndex] = aggregate
      ? { ...aggregate, hasFilings: true }
      : {
          date: day,
          signal: 0,
          filings: 0,
          buys: 0,
          sells: 0,
          hasFilings: false,
          records: [],
        };

    weekIndex += 1;
    if (weekIndex === 5) {
      weeks.push(currentWeek);
      currentWeek = new Array(5).fill(null);
      weekIndex = 0;
    }
  }

  if (currentWeek.some((cell) => cell !== null)) {
    weeks.push(currentWeek);
  }

  const monthLabel = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(year, month, 1));

  return { monthLabel, month, year, calendarData: weeks, visibleRecords: filtered };
};

const flattenDays = (data) => data.flat().filter((day) => day && day.hasFilings);

const computeDashboardStats = (calendarData, records) => {
  const activeDays = flattenDays(calendarData);
  const netSignal = activeDays.reduce((sum, day) => sum + day.signal, 0);
  const totalFilings = records.length;
  const totalBuyValue = records.filter((record) => record.isBuy).reduce((sum, record) => sum + record.value, 0);
  const totalSellValue = records.filter((record) => record.isSell).reduce((sum, record) => sum + record.value, 0);

  return {
    netSignal,
    activeDays: activeDays.length,
    totalFilings,
    totalBuyValue,
    totalSellValue,
  };
};

const saveWatchlist = (tickers) => localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(tickers));

const readWatchlist = () => {
  try {
    const parsed = JSON.parse(localStorage.getItem(WATCHLIST_STORAGE_KEY) || '[]');
    return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
  } catch {
    return [];
  }
};

const evaluateAlerts = (records, watchlist) => {
  const LARGE_VALUE_THRESHOLD = 500000;
  const alerts = [];

  const largeTrades = records.filter((record) => record.value >= LARGE_VALUE_THRESHOLD);
  if (largeTrades.length > 0) {
    alerts.push(`${largeTrades.length} large filing${largeTrades.length === 1 ? '' : 's'} above $500K detected.`);
  }

  const watchlistHits = records.filter((record) => watchlist.includes(record.ticker));
  if (watchlistHits.length > 0) {
    alerts.push(`Watchlist activity on ${new Set(watchlistHits.map((record) => record.ticker)).size} ticker(s).`);
  }

  const clusterBuys = new Map();
  records.filter((record) => record.isBuy).forEach((record) => {
    const count = clusterBuys.get(record.ticker) ?? new Set();
    count.add(record.insider);
    clusterBuys.set(record.ticker, count);
  });

  clusterBuys.forEach((insiders, ticker) => {
    if (insiders.size >= 2) {
      alerts.push(`Cluster buying signal for ${ticker}: ${insiders.size} insiders bought.`);
    }
  });

  return alerts;
};

const renderHeader = (stats, monthLabel, currentFilter, onFilterChange, onUpload) => {
  const header = createEl('header', 'top-bar');
  const controls = createEl('div', 'month-controls');
  controls.append(createEl('h1', null, `${monthLabel} Insider Tracker`));

  const filterGroup = createEl('div', 'filter-group');
  ['all', 'buy', 'sell'].forEach((value) => {
    const button = createEl('button', `pill-button ${currentFilter === value ? 'active' : ''}`, value.toUpperCase());
    button.type = 'button';
    button.addEventListener('click', () => onFilterChange(value));
    filterGroup.append(button);
  });

  const uploadLabel = createEl('label', 'upload-button', 'Upload insider CSV');
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.csv';
  input.addEventListener('change', (event) => {
    const [file] = event.target.files;
    if (file) {
      onUpload(file);
    }
    event.target.value = '';
  });
  uploadLabel.append(input);

  controls.append(filterGroup, uploadLabel);

  const highlight = createEl('div', 'monthly-highlight');
  highlight.append(
    createEl('span', 'label', 'Signal snapshot'),
    createEl('div', 'stats', ''),
  );

  const statsRow = highlight.querySelector('.stats');
  statsRow.append(
    createEl('span', `net ${sentimentClass(stats.netSignal)}`, formatCurrency(stats.netSignal)),
    createEl('span', 'divider', '•'),
    createEl('span', 'days', `${stats.totalFilings} ${pluralize('filing', stats.totalFilings)}`),
  );

  header.append(controls, highlight);
  return header;
};

const renderCalendarPanel = (calendarData, onDaySelect) => {
  const panel = createEl('section', 'calendar-panel');
  const header = createEl('div', 'calendar-header');
  ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].forEach((dayLabel) => header.append(createEl('span', null, dayLabel)));

  const grid = createEl('div', 'calendar-grid');
  let selectedCard = null;

  const selectCard = (card, day) => {
    if (selectedCard) {
      selectedCard.classList.remove('selected');
    }
    selectedCard = card;
    selectedCard.classList.add('selected');
    onDaySelect(day);
  };

  let firstSelectable = null;

  calendarData.forEach((week) => {
    week.forEach((day) => {
      if (!day) {
        grid.append(createEl('div', 'day-card empty', 'No data'));
        return;
      }

      const classes = ['day-card', day.hasFilings ? sentimentClass(day.signal) : 'neutral', day.hasFilings ? 'interactive' : 'no-trades'];
      const card = createEl('div', classes.join(' '));
      const date = createEl('div', 'date', String(day.date));
      const signal = createEl('div', 'profit', day.hasFilings ? formatCurrency(day.signal) : '—');
      const details = createEl('div', 'details');
      details.textContent = day.hasFilings
        ? `${day.filings} filings • ${day.buys} buys / ${day.sells} sells`
        : 'No filings';

      card.append(date, signal, details);

      if (day.hasFilings) {
        card.tabIndex = 0;
        card.addEventListener('click', () => selectCard(card, day));
        card.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            selectCard(card, day);
          }
        });
        if (!firstSelectable) {
          firstSelectable = { card, day };
        }
      }

      grid.append(card);
    });
  });

  if (firstSelectable) {
    selectCard(firstSelectable.card, firstSelectable.day);
  }

  panel.append(header, grid);
  return panel;
};

const renderSidebar = (calendarData, stats, records, watchlist, onWatchlistUpdate) => {
  const panel = createEl('aside', 'weekly-panel');

  const summary = createEl('div', `weekly-summary ${sentimentClass(stats.netSignal)}`);
  summary.append(
    createEl('span', 'title', 'Net insider signal'),
    createEl('span', 'value', formatCurrency(stats.netSignal)),
    createEl('span', 'meta', `${stats.activeDays} active days • Buy ${formatCurrency(stats.totalBuyValue)} / Sell ${formatCurrency(stats.totalSellValue)}`),
  );
  panel.append(summary);

  const watchlistCard = createEl('div', 'week-card neutral');
  watchlistCard.append(createEl('div', 'meta', 'Watchlist'));
  const input = document.createElement('input');
  input.className = 'watchlist-input';
  input.placeholder = 'e.g. NVDA, TSLA, AAPL';
  input.value = watchlist.join(', ');
  input.addEventListener('change', () => {
    const tickers = input.value
      .split(',')
      .map((ticker) => ticker.trim().toUpperCase())
      .filter(Boolean);
    saveWatchlist(tickers);
    onWatchlistUpdate(tickers);
  });
  watchlistCard.append(input);
  panel.append(watchlistCard);

  const alerts = evaluateAlerts(records, watchlist);
  const alertCard = createEl('div', 'week-card neutral');
  alertCard.append(createEl('div', 'meta', `Alerts (${alerts.length})`));
  if (alerts.length === 0) {
    alertCard.append(createEl('div', 'value', 'No active alerts'));
  } else {
    const list = createEl('ul', 'alert-list');
    alerts.forEach((alert) => list.append(createEl('li', null, alert)));
    alertCard.append(list);
  }
  panel.append(alertCard);

  calendarData.forEach((week, index) => {
    const filings = week.filter((day) => day && day.hasFilings);
    const weekSignal = filings.reduce((sum, day) => sum + day.signal, 0);
    const weekCard = createEl('div', `week-card ${sentimentClass(weekSignal)}`);
    weekCard.append(
      createEl('div', 'meta', `Week ${index + 1} • ${filings.length} filing days`),
      createEl('div', 'value', formatCurrency(weekSignal)),
    );
    panel.append(weekCard);
  });

  return panel;
};

const renderDetailPanel = () => {
  const panel = createEl('section', 'trade-detail-panel');
  panel.append(createEl('div', 'trade-detail-placeholder', 'Select a day to inspect SEC insider filings.'));
  return panel;
};

const formatDayLabel = (day, month, year) =>
  new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' }).format(new Date(year, month, day));

const renderRecordItem = (record) => {
  const item = createEl('article', 'trade-item');
  const header = createEl('div', 'trade-item-header');
  header.append(
    createEl('span', 'trade-instrument', `${record.ticker} • ${record.insider}`),
    createEl('span', `trade-amount ${sentimentClass(record.signedValue)}`, formatCurrency(record.signedValue)),
  );

  const description = createEl('div', 'trade-item-description', `${record.transactionType} • ${record.role} • ${record.form}`);
  const meta = createEl('div', 'trade-item-meta', `${record.shares.toLocaleString()} shares • ${record.ownership} ownership`);
  item.append(header, description, meta);
  return item;
};

const updateDetailPanel = (panel, day, month, year) => {
  panel.innerHTML = '';

  if (!day || !day.hasFilings) {
    panel.append(createEl('div', 'trade-detail-placeholder', 'No filings for this date.'));
    return;
  }

  const title = createEl('h2', 'trade-detail-title', `Insider filings for ${formatDayLabel(day.date, month, year)}`);
  const summary = createEl('div', 'trade-detail-summary');
  const buyRate = day.filings ? (day.buys / day.filings) * 100 : 0;

  summary.append(
    createEl('span', `summary-profit ${sentimentClass(day.signal)}`, formatCurrency(day.signal)),
    createEl('span', 'summary-meta', `${day.filings} filings • ${day.buys} buys • ${day.sells} sells • ${formatPercent(buyRate)} buy-rate`),
  );

  const list = createEl('div', 'trade-list');
  day.records.forEach((record) => list.append(renderRecordItem(record)));

  panel.append(title, summary, list);
};

const showError = (message) => {
  if (!appRoot) {
    return;
  }

  appRoot.querySelectorAll('.upload-feedback').forEach((node) => node.remove());
  appRoot.prepend(createEl('div', 'upload-feedback error', message));
};

const fetchTradeRecords = async () => {
  const response = await fetch('./trades.csv', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch data: ${response.status}`);
  }
  return parseCsv(await response.text());
};

const state = {
  rawRecords: [],
  normalizedRecords: [],
  filter: 'all',
  watchlist: readWatchlist(),
};

const renderApp = () => {
  if (!appRoot) {
    return;
  }

  const calendarInfo = buildCalendarData(state.normalizedRecords, state.filter);
  const stats = computeDashboardStats(calendarInfo.calendarData, calendarInfo.visibleRecords);
  const detailPanel = renderDetailPanel();

  const rerenderWithFilter = (filter) => {
    state.filter = filter;
    renderApp();
  };

  const header = renderHeader(stats, calendarInfo.monthLabel, state.filter, rerenderWithFilter, async (file) => {
    try {
      const uploaded = parseCsv(await file.text());
      const normalized = normalizeInsiderRecords(uploaded);
      if (normalized.length === 0) {
        throw new Error('Uploaded CSV has no valid insider filing rows.');
      }
      state.rawRecords = uploaded;
      state.normalizedRecords = normalized;
      renderApp();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showError(`Unable to load uploaded file: ${message}`);
    }
  });

  const layout = createEl('main', 'layout');
  layout.append(
    renderCalendarPanel(calendarInfo.calendarData, (day) => updateDetailPanel(detailPanel, day, calendarInfo.month, calendarInfo.year)),
    renderSidebar(calendarInfo.calendarData, stats, calendarInfo.visibleRecords, state.watchlist, (watchlist) => {
      state.watchlist = watchlist;
      renderApp();
    }),
  );

  appRoot.innerHTML = '';
  appRoot.append(header, layout, detailPanel);
};

const initialize = async () => {
  appRoot = document.getElementById('root');
  if (!appRoot) {
    return;
  }

  appRoot.innerHTML = '';
  appRoot.append(createEl('div', 'loading-state', 'Loading insider filings…'));

  try {
    state.rawRecords = await fetchTradeRecords();
    state.normalizedRecords = normalizeInsiderRecords(state.rawRecords);

    if (state.normalizedRecords.length === 0) {
      throw new Error('No valid insider records found in CSV.');
    }

    renderApp();
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    appRoot.innerHTML = '';
    appRoot.append(createEl('div', 'error-state', `Unable to load insider data: ${message}`));
  }
};

initialize();
