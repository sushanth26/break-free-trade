import { useMemo } from 'react';
import calendarData, { DayStats } from './data/calendar';
import { formatCurrency, formatPercent, pluralize, sentimentClass } from './utils/format';

const dayKey = (weekIndex: number, dayIndex: number): string => `${weekIndex}-${dayIndex}`;

const App = (): JSX.Element => {
  const { monthlyNet, monthlyDays, avgDaily } = useMemo(() => {
    const flattened: DayStats[] = [];

    calendarData.forEach((week) => {
      week.forEach((day) => {
        if (day) {
          flattened.push(day);
        }
      });
    });

    const totalNet = flattened.reduce((sum, day) => sum + day.profit, 0);
    const totalDays = flattened.length;
    const averageDaily = totalNet / (totalDays || 1);

    return {
      monthlyNet: totalNet,
      monthlyDays: totalDays,
      avgDaily: averageDaily,
    };
  }, []);

  const monthSentiment = sentimentClass(monthlyNet);

  return (
    <div className="app-shell">
      <header className="top-bar">
        <div className="month-controls">
          <h1>October 2025</h1>
          <button type="button" className="pill-button">
            <span className="dot" />
            This month
          </button>
        </div>
        <div className="monthly-highlight">
          <span className="label">Monthly stats</span>
          <div className="stats">
            <span className={`net ${monthSentiment}`} id="monthly-net">
              {formatCurrency(monthlyNet)}
            </span>
            <span className="divider">•</span>
            <span className="days" id="monthly-days">
              {`${monthlyDays} ${pluralize('day', monthlyDays)}`}
            </span>
          </div>
        </div>
      </header>

      <main className="layout">
        <section className="calendar-panel">
          <div className="calendar-header">
            <span>Mon</span>
            <span>Tue</span>
            <span>Wed</span>
            <span>Thu</span>
            <span>Fri</span>
          </div>
          <div className="calendar-grid" id="calendar-grid">
            {calendarData.map((week, weekIndex) =>
              week.map((day, dayIndex) => {
                if (!day) {
                  return (
                    <div key={dayKey(weekIndex, dayIndex)} className="day-card empty">
                      No data
                    </div>
                  );
                }

                const sentiment = sentimentClass(day.profit);

                return (
                  <div key={dayKey(weekIndex, dayIndex)} className={`day-card ${sentiment}`}>
                    <div className="date">{day.date}</div>
                    <div className="profit">{formatCurrency(day.profit)}</div>
                    <div className="details">
                      <span>
                        {day.trades} {pluralize('trade', day.trades)}
                      </span>
                      <span>{`${formatPercent(day.winRate)} win rate`}</span>
                    </div>
                  </div>
                );
              }),
            )}
          </div>
        </section>
        <aside className="weekly-panel" id="weekly-panel">
          <div className={`weekly-summary ${monthSentiment}`}>
            <span className="title">Monthly net</span>
            <span className="value">{formatCurrency(monthlyNet)}</span>
            <span className="meta">
              {`${monthlyDays} active ${pluralize('day', monthlyDays)} • Avg ${formatCurrency(avgDaily)}`}
            </span>
          </div>
          {calendarData.map((week, index) => {
            const trades = week.filter((day): day is DayStats => day !== null);
            const weekDays = trades.length;
            const weekNet = trades.reduce((sum, day) => sum + day.profit, 0);
            const weekSentiment = sentimentClass(weekNet);

            return (
              <div key={`week-${index}`} className={`week-card ${weekSentiment}`}>
                <div className="meta">
                  <span>{`Week ${index + 1}`}</span>
                  <span>{`${weekDays} ${pluralize('day', weekDays)}`}</span>
                </div>
                <div className="value">{formatCurrency(weekNet)}</div>
              </div>
            );
          })}
        </aside>
      </main>
    </div>
  );
};

export default App;
