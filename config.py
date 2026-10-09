"""All settings for the Day-Trading Agent.

Distances are multiples of the stock's 5-minute ATR (from StockProfile),
never fixed dollars. Modules read from here; no magic numbers elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- market / time
TZ = "America/New_York"
PREMARKET_START = "04:00"
REGULAR_OPEN = "09:30"
REGULAR_CLOSE = "16:00"
AFTERHOURS_END = "20:00"

BASE_TIMEFRAME = "5m"
TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "D")

# ---------------------------------------------------------------- universe
BUILD_STOCKS = ("SPY", "QQQ", "DELL", "SOXL", "NVDA")
# 10 more names must be picked before tuning starts (open item in the plan).
VALIDATION_STOCKS = ("AMD", "TSLA", "META", "AAPL", "MSFT", "AMZN", "AVGO", "MU", "PLTR", "COIN")
CONTEXT_SYMBOLS = ("SPY", "QQQ", "SMH", "VIXY")

# ---------------------------------------------------------------- data split
TRAIN_START = "2025-10-01"
TRAIN_END = "2026-06-30"
OOS_START = "2026-07-01"
OOS_END = "2026-10-16"
HISTORY_MONTHS = 12

# ---------------------------------------------------------------- data checks
ALIGN_CLOSE_TOL_PCT = 0.05     # Alpaca vs Webull closes within 0.05%
ALIGN_VOLUME_TOL_PCT = 10.0    # volume within 10%
WEBULL_MAX_BARS = 1200         # history endpoint cap

# ---------------------------------------------------------------- profile (module 1)
ATR_PERIOD = 14                # Wilder, same as TradingView
DAILY_ATR_PERIOD = 14
RVOL_LOOKBACK_DAYS = 20        # baseline volume per time-of-day slot
OPENING_RANGE_MINUTES = 15

# Round-number spacing by price: (upper price bound, step)
ROUND_STEPS = ((20.0, 0.50), (100.0, 1.0), (300.0, 2.50), (float("inf"), 5.0))

# ---------------------------------------------------------------- indicators
EMA_CLOUD_FAST = (5, 12)
EMA_CLOUD_SLOW = (34, 50)


# ---------------------------------------------------------------- zones (module 2)
@dataclass(frozen=True)
class ZoneConfig:
    """Support/resistance channel settings (TradingView SR-channels style).

    Backtest 1 grid: pivot_period 5/10/20 x channel_width_pct 1/2/3 x min_strength 1/2.
    """
    pivot_period: int = 10          # bars each side; pivot confirms pivot_period bars later
    channel_width_pct: float = 2.0  # max zone width as % of the range_bars high-low range
    min_strength: int = 1           # min pivots in a zone (each pivot = PIVOT_WEIGHT)
    max_zones: int = 6
    loopback: int = 290             # bars of pivots/touches considered
    range_bars: int = 300           # bars for the width reference range


ZONE_DEFAULT = ZoneConfig()
ZONE_PIVOT_WEIGHT = 20             # strength points per pivot in a zone
ZONE_MERGE_OVERLAP = True          # merge overlapping zones across timeframes

ZONE_GRID_PIVOT_PERIODS = (5, 10, 20)
ZONE_GRID_CHANNEL_WIDTHS = (1.0, 2.0, 3.0)
ZONE_GRID_MIN_STRENGTHS = (1, 2)
ZONE_GRID_TIMEFRAME_COMBOS = (
    ("5m",), ("15m",), ("30m",), ("1h",),
    ("5m", "30m"), ("5m", "1h"), ("15m", "1h"), ("5m", "30m", "D"),
)

# Zone score shown on charts = w_s * strength - w_b * break risk
ZONE_W_STRENGTH = 1.0
ZONE_W_BREAK = 1.0
ZONE_SCORE_STRONG = 80
ZONE_SCORE_MEDIUM = 50

# Touch outcome label (Backtest 1): held = moved HOLD_MOVE_ATR away before breaking by BREAK_ATR
HOLD_MOVE_ATR = 0.5
BREAK_ATR = 0.5

# ---------------------------------------------------------------- bounce / trade rules
REJECTION_WICK_PCT = 0.50
REJECTION_CLOSE_ATR = 0.1
FOLLOW_THROUGH_ATR = 0.5
FOLLOW_THROUGH_BARS = 2
MAX_ENTRY_DIST_ATR = 0.5
STOP_BUFFER_ATR = 0.1
FRONT_RUN_ATR = 0.1
ENTRY_MODE = "confirmed"           # "confirmed" (stage 3) or "early" (stage 2 close)
ENTRY_CUTOFF = "15:45"
PREMARKET_SIZE = 0.5
PREMARKET_MAX_SPREAD_ATR = 0.1
MAX_FIRST_ZONE_R = 5.0
MIN_R_TO_T1_APLUS = 3.0
APLUS_MIN_RVOL = 1.5
NEWS_WINDOW = (-5, 15)             # minutes around macro events: before, after

# Open items: trader to set these.
RISK_PER_TRADE = 100.0             # $ risk per trade
MAX_DAILY_LOSS = 300.0             # $
MAX_CONSECUTIVE_LOSSES = 2

# ---------------------------------------------------------------- fills / costs
SLIPPAGE_PCT = 0.02                # % of price on every fill
COMMISSION_PER_SHARE = 0.005
TICK_SIZE = 0.01

# ---------------------------------------------------------------- backtest pass criteria
PASS_MIN_WIN_RATE = 0.60
TARGET_WIN_RATE = 0.65
PASS_MIN_TRADES = 200
PASS_MIN_EXPECTANCY_R = 0.25
PASS_MIN_PROFIT_FACTOR = 1.5
PASS_MAX_DRAWDOWN_R = 10.0

# ---------------------------------------------------------------- AI / live
CLAUDE_MODEL = "claude-sonnet-5-5"
CLAUDE_TIMEOUT_S = 10
HEARTBEAT_TIMEOUT_S = 60

# ---------------------------------------------------------------- paths
CACHE_DIR = "cache"                # Parquet history cache
ARCHIVE_DIR = "archive"            # daily Webull CSV archive
DB_PATH = "logs/agent.sqlite"

