const calendarData = [
  [
    null,
    null,
    { date: 1, profit: -679, trades: 7, winRate: -12.4 },
    { date: 2, profit: -990, trades: 7, winRate: -21.6 },
    { date: 3, profit: -121, trades: 5, winRate: -3.1 },
  ],
  [
    { date: 6, profit: 1520, trades: 8, winRate: 62.5 },
    { date: 7, profit: -743, trades: 9, winRate: -18.8 },
    { date: 8, profit: -304, trades: 8, winRate: -9.7 },
    { date: 9, profit: -121, trades: 7, winRate: -5.4 },
    { date: 10, profit: 152, trades: 5, winRate: 71.4 },
  ],
  [
    { date: 13, profit: 1650, trades: 8, winRate: 72.5 },
    { date: 14, profit: 277, trades: 6, winRate: 66.7 },
    { date: 15, profit: 315, trades: 6, winRate: 83.3 },
    { date: 16, profit: -67.6, trades: 6, winRate: -11.4 },
    { date: 17, profit: -16.6, trades: 6, winRate: -3.2 },
  ],
  [
    { date: 20, profit: 111, trades: 5, winRate: 60 },
    { date: 21, profit: 231, trades: 6, winRate: 66.7 },
    { date: 22, profit: 297, trades: 7, winRate: 71.4 },
    { date: 23, profit: 126, trades: 5, winRate: 80 },
    { date: 24, profit: -58.5, trades: 5, winRate: -16.7 },
  ],
  [
    { date: 27, profit: -1030, trades: 10, winRate: -33.3 },
    { date: 28, profit: -56.4, trades: 5, winRate: -16.7 },
    { date: 29, profit: -152, trades: 7, winRate: -14.3 },
    { date: 30, profit: 0, trades: 4, winRate: 0 },
    { date: 31, profit: -432, trades: 6, winRate: -22.1 },
  ],
];

const calendarGrid = document.getElementById('calendar-grid');
const weeklyPanel = document.getElementById('weekly-panel');

const flattenDays = calendarData.flat().filter(Boolean);

const monthlyNet = flattenDays.reduce((sum, day) => sum + day.profit, 0);
const monthlyDays = flattenDays.length;
const avgDaily = monthlyNet / (monthlyDays || 1);

const monthlyNetEl = document.getElementById('monthly-net');
const monthlyDaysEl = document.getElementById('monthly-days');

monthlyNetEl.textContent = formatCurrency(monthlyNet);
monthlyNetEl.classList.toggle('positive', monthlyNet > 0);
monthlyNetEl.classList.toggle('negative', monthlyNet < 0);
monthlyDaysEl.textContent = `${monthlyDays} ${monthlyDays === 1 ? 'day' : 'days'}`;

calendarData.forEach((week) => {
  week.forEach((day) => {
    const card = document.createElement('div');

    if (!day) {
      card.className = 'day-card empty';
      card.textContent = 'No data';
      calendarGrid.appendChild(card);
      return;
    }

    card.classList.add('day-card', sentimentClass(day.profit));
    card.innerHTML = `
      <div class="date">${day.date}</div>
      <div class="profit">${formatCurrency(day.profit)}</div>
      <div class="details">
        <span>${day.trades} ${pluralize('trade', day.trades)}</span>
        <span>${formatPercent(day.winRate)} win rate</span>
      </div>
    `;

    calendarGrid.appendChild(card);
  });
});

renderWeeklyPanel();

function renderWeeklyPanel() {
  const summary = document.createElement('div');
  summary.className = `weekly-summary ${monthlyNet > 0 ? 'positive' : monthlyNet < 0 ? 'negative' : 'neutral'}`;
  summary.innerHTML = `
    <span class="title">Monthly net</span>
    <span class="value">${formatCurrency(monthlyNet)}</span>
    <span class="meta">${monthlyDays} active ${pluralize('day', monthlyDays)} • Avg ${formatCurrency(avgDaily)}</span>
  `;
  weeklyPanel.appendChild(summary);

  calendarData.forEach((week, index) => {
    const trades = week.filter(Boolean);
    const weekDays = trades.length;
    const weekNet = trades.reduce((sum, day) => sum + day.profit, 0);

    const weekCard = document.createElement('div');
    weekCard.className = `week-card ${weekNet > 0 ? 'positive' : weekNet < 0 ? 'negative' : 'neutral'}`;
    weekCard.innerHTML = `
      <div class="meta">
        <span>Week ${index + 1}</span>
        <span>${weekDays} ${pluralize('day', weekDays)}</span>
      </div>
      <div class="value">${formatCurrency(weekNet)}</div>
    `;

    weeklyPanel.appendChild(weekCard);
  });
}

function formatCurrency(value) {
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  const absValue = Math.abs(value);
  let formatted;

  if (absValue >= 1000) {
    const compact = absValue / 1000;
    formatted = `$${trimZeros(compact.toFixed(compact >= 10 ? 0 : 2))}K`;
  } else if (absValue >= 100) {
    formatted = `$${trimZeros(absValue.toFixed(0))}`;
  } else if (absValue === 0) {
    formatted = '$0';
  } else {
    formatted = `$${trimZeros(absValue.toFixed(1))}`;
  }

  return sign ? `${sign}${formatted}` : formatted;
}

function trimZeros(value) {
  return Number(value).toString();
}

function formatPercent(value) {
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  const absValue = Math.abs(value);
  const formatted = absValue >= 10 ? absValue.toFixed(1) : absValue.toFixed(1);
  return `${sign}${trimZeros(formatted)}%`;
}

function pluralize(word, count) {
  return count === 1 ? word : `${word}s`;
}

function sentimentClass(value) {
  if (value > 0) return 'positive';
  if (value < 0) return 'negative';
  return 'neutral';
}
