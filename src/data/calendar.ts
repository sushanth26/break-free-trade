export interface DayStats {
  date: number;
  profit: number;
  trades: number;
  winRate: number;
}

export type WeekStats = Array<DayStats | null>;

const calendarData: WeekStats[] = [
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

export default calendarData;
