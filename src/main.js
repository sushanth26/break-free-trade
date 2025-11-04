import { formatCurrency, formatPercent, pluralize, sentimentClass } from './utils/format.js';

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

const parseDate = (value) => {
  if (!value) {
    return null;
  }

  const parts = value.split('/');
  if (parts.length !== 3) {
    return null;
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

const formatIsoKey = (year, month, day) =>
  `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

const parseAmount = (value) => {
  if (!value) {
    return 0;
  }

  const cleaned = value.replace(/[$,]/g, '');
  const negative = cleaned.startsWith('(') && cleaned.endsWith(')');
  const numeric = Number.parseFloat(cleaned.replace(/[()]/g, ''));

  if (!Number.isFinite(numeric)) {
    return 0;
  }

  return negative ? -numeric : numeric;
};

const aggregateDailyTrades = (records, month, year) => {
  const dailyMap = new Map();

  records.forEach((record) => {
    const date = parseDate(record['Activity Date']);
    if (!date || date.getFullYear() !== year || date.getMonth() !== month) {
      return;
    }

    const amount = parseAmount(record.Amount);
    const key = formatIsoKey(year, month, date.getDate());
    const aggregate = dailyMap.get(key) ?? { total: 0, trades: 0, wins: 0 };

    aggregate.total += amount;
    aggregate.trades += 1;
    if (amount > 0) {
      aggregate.wins += 1;
    }

    dailyMap.set(key, aggregate);
  });

  return dailyMap;
};

const createCalendarMatrix = (dailyMap, month, year) => {
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  let firstWeekday = null;
  let firstWeekdayIndex = 0;

  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = new Date(year, month, day);
    const dayOfWeek = date.getDay();

    if (dayOfWeek >= 1 && dayOfWeek <= 5) {
      firstWeekday = day;
      firstWeekdayIndex = dayOfWeek - 1;
      break;
    }
  }

  if (!firstWeekday) {
    return [];
  }

  const weeks = [];
  let currentWeek = new Array(5).fill(null);
  let weekIndex = firstWeekdayIndex;

  for (let index = 0; index < firstWeekdayIndex; index += 1) {
    currentWeek[index] = null;
  }

  let day = firstWeekday;
  while (day <= daysInMonth) {
    const date = new Date(year, month, day);
    const key = formatIsoKey(year, month, day);
    const aggregate = dailyMap.get(key);

    currentWeek[weekIndex] = aggregate
      ? {
          date: day,
          profit: aggregate.total,
          trades: aggregate.trades,
          winRate: aggregate.trades ? (aggregate.wins / aggregate.trades) * 100 : 0,
          hasTrades: true,
        }
      : {
          date: day,
          profit: 0,
          trades: 0,
          winRate: 0,
          hasTrades: false,
        };

    weekIndex += 1;

    if (weekIndex === 5) {
      weeks.push(currentWeek);
      currentWeek = new Array(5).fill(null);
      weekIndex = 0;
    }

    day += 1;

    while (day <= daysInMonth) {
      const dayOfWeek = new Date(year, month, day).getDay();
      if (dayOfWeek === 0 || dayOfWeek === 6) {
        day += 1;
        continue;
      }
      break;
    }
  }

  if (weekIndex > 0 || currentWeek.some((cell) => cell !== null)) {
    weeks.push(currentWeek);
  }

  return weeks;
};

const formatMonthLabel = (month, year) =>
  new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(year, month, 1));

const buildCalendarData = (records) => {
  const tradeDates = records
    .map((record) => parseDate(record['Activity Date']))
    .filter((date) => date instanceof Date && !Number.isNaN(date.getTime()))
    .sort((a, b) => a - b);

  if (tradeDates.length === 0) {
    throw new Error('No valid trade dates found in CSV.');
  }

  const month = tradeDates[0].getMonth();
  const year = tradeDates[0].getFullYear();
  const dailyMap = aggregateDailyTrades(records, month, year);
  const calendarData = createCalendarMatrix(dailyMap, month, year);

  return {
    calendarData,
    monthLabel: formatMonthLabel(month, year),
  };
};

const fetchCalendarData = async () => {
  const response = await fetch('./trades.csv', { cache: 'no-store' });

  if (!response.ok) {
    throw new Error(`Failed to fetch trade data: ${response.status}`);
  }

  const text = await response.text();
  const records = parseCsv(text);

  if (records.length === 0) {
    throw new Error('Trade CSV is empty.');
  }

  return buildCalendarData(records);
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

const flattenDays = (data) => data.flat().filter((day) => day && day.hasTrades);

const computeMonthlyStats = (data) => {
  const days = flattenDays(data);
  const monthlyNet = days.reduce((sum, day) => sum + day.profit, 0);
  const monthlyDays = days.length;
  const avgDaily = monthlyNet / (monthlyDays || 1);

  return { monthlyNet, monthlyDays, avgDaily };
};

const renderMonthlyHeader = (stats, monthLabel) => {
  const header = createEl('header', 'top-bar');

  const monthControls = createEl('div', 'month-controls');
  const title = createEl('h1', null, monthLabel);
  const button = createEl('button', 'pill-button');
  button.type = 'button';

  const dot = createEl('span', 'dot');
  const label = document.createTextNode('This month');
  button.append(dot, label);
  monthControls.append(title, button);

  const monthlyHighlight = createEl('div', 'monthly-highlight');
  const labelEl = createEl('span', 'label', 'Monthly stats');
  const statsContainer = createEl('div', 'stats');
  const net = createEl('span', `net ${sentimentClass(stats.monthlyNet)}`, formatCurrency(stats.monthlyNet));
  net.id = 'monthly-net';
  const divider = createEl('span', 'divider', '•');
  const days = createEl(
    'span',
    'days',
    `${stats.monthlyDays} ${pluralize('day', stats.monthlyDays)}`,
  );
  days.id = 'monthly-days';

  statsContainer.append(net, divider, days);
  monthlyHighlight.append(labelEl, statsContainer);

  header.append(monthControls, monthlyHighlight);
  return header;
};

const renderCalendarPanel = (data) => {
  const panel = createEl('section', 'calendar-panel');
  const header = createEl('div', 'calendar-header');
  ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].forEach((day) => {
    header.append(createEl('span', null, day));
  });

  const grid = createEl('div', 'calendar-grid');

  data.forEach((week) => {
    week.forEach((day) => {
      if (!day) {
        const empty = createEl('div', 'day-card empty', 'No data');
        grid.append(empty);
        return;
      }

      const classes = ['day-card'];
      if (day.hasTrades) {
        classes.push(sentimentClass(day.profit));
      } else {
        classes.push('neutral', 'no-trades');
      }

      const card = createEl('div', classes.join(' '));
      const date = createEl('div', 'date', String(day.date));
      const profit = createEl('div', 'profit', day.hasTrades ? formatCurrency(day.profit) : '—');
      const details = createEl('div', 'details');

      if (day.hasTrades) {
        const trades = createEl('span', null, `${day.trades} ${pluralize('trade', day.trades)}`);
        const winRate = createEl('span', null, `${formatPercent(day.winRate)} win rate`);
        details.append(trades, winRate);
      } else {
        details.textContent = 'No trades recorded';
      }

      card.append(date, profit, details);
      grid.append(card);
    });
  });

  panel.append(header, grid);
  return panel;
};

const renderWeeklyPanel = (data, stats) => {
  const panel = createEl('aside', 'weekly-panel');

  const summary = createEl('div', `weekly-summary ${sentimentClass(stats.monthlyNet)}`);
  summary.append(
    createEl('span', 'title', 'Monthly net'),
    createEl('span', 'value', formatCurrency(stats.monthlyNet)),
    createEl(
      'span',
      'meta',
      `${stats.monthlyDays} active ${pluralize('day', stats.monthlyDays)} • Avg ${formatCurrency(stats.avgDaily)}`,
    ),
  );

  panel.append(summary);

  data.forEach((week, index) => {
    const trades = week.filter((day) => day && day.hasTrades);
    const weekDays = trades.length;
    const weekNet = trades.reduce((sum, day) => sum + day.profit, 0);
    const weekCard = createEl('div', `week-card ${sentimentClass(weekNet)}`);
    const meta = createEl('div', 'meta');
    meta.append(
      createEl('span', null, `Week ${index + 1}`),
      createEl('span', null, `${weekDays} ${pluralize('day', weekDays)}`),
    );
    weekCard.append(meta, createEl('div', 'value', formatCurrency(weekNet)));
    panel.append(weekCard);
  });

  return panel;
};

const buildAppShell = (calendarData, monthLabel) => {
  const appShell = createEl('div', 'app-shell');
  const stats = computeMonthlyStats(calendarData);
  const header = renderMonthlyHeader(stats, monthLabel);
  const layout = createEl('main', 'layout');
  layout.append(renderCalendarPanel(calendarData), renderWeeklyPanel(calendarData, stats));
  appShell.append(header, layout);
  return appShell;
};

const initialize = async () => {
  const root = document.getElementById('root');
  if (!root) {
    return;
  }

  root.innerHTML = '';
  const loading = createEl('div', 'loading-state', 'Loading trade data…');
  root.append(loading);

  try {
    const { calendarData, monthLabel } = await fetchCalendarData();
    root.innerHTML = '';
    root.append(buildAppShell(calendarData, monthLabel));
  } catch (error) {
    console.error(error);
    root.innerHTML = '';
    root.append(createEl('div', 'error-state', 'Unable to load trade data.'));
  }
};

initialize();
