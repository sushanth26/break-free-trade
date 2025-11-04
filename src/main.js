import calendarData from './data/calendar.js';
import { formatCurrency, formatPercent, pluralize, sentimentClass } from './utils/format.js';

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

const flattenDays = (data) => data.flat().filter((day) => day !== null);

const computeMonthlyStats = (data) => {
  const days = flattenDays(data);
  const monthlyNet = days.reduce((sum, day) => sum + day.profit, 0);
  const monthlyDays = days.length;
  const avgDaily = monthlyNet / (monthlyDays || 1);

  return { monthlyNet, monthlyDays, avgDaily };
};

const renderMonthlyHeader = (stats) => {
  const header = createEl('header', 'top-bar');

  const monthControls = createEl('div', 'month-controls');
  const title = createEl('h1', null, 'October 2025');
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

      const sentiment = sentimentClass(day.profit);
      const card = createEl('div', `day-card ${sentiment}`);
      const date = createEl('div', 'date', String(day.date));
      const profit = createEl('div', 'profit', formatCurrency(day.profit));
      const details = createEl('div', 'details');
      const trades = createEl('span', null, `${day.trades} ${pluralize('trade', day.trades)}`);
      const winRate = createEl('span', null, `${formatPercent(day.winRate)} win rate`);
      details.append(trades, winRate);
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
    const trades = week.filter((day) => day !== null);
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

const renderApp = () => {
  const root = document.getElementById('root');
  if (!root) {
    return;
  }

  root.innerHTML = '';
  const appShell = createEl('div', 'app-shell');
  const stats = computeMonthlyStats(calendarData);

  const header = renderMonthlyHeader(stats);
  const layout = createEl('main', 'layout');
  layout.append(renderCalendarPanel(calendarData), renderWeeklyPanel(calendarData, stats));

  appShell.append(header, layout);
  root.append(appShell);
};

renderApp();
