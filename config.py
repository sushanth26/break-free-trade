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
# DELL dropped 2026-10-09: Alpaca thin-bar closes differ from Webull/Robinhood (alignment p95 0.14 ATR).
BUILD_STOCKS = ("SPY", "QQQ", "SOXL", "NVDA")
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
ALIGN_PRICE_P95_ATR = 0.1      # Alpaca vs Webull close/high/low: 95% of diffs within 0.1 ATR (engine precision)
ALIGN_PRICE_MAX_ATR = 0.5      # outlier: a diff above 0.5 ATR ...
ALIGN_OUTLIER_MAX_SHARE = 0.005  # ... allowed on at most 0.5% of bars (a single bad print)
ALIGN_VOLUME_TOL_PCT = 10.0    # a bar's volume "matches" within 10%
ALIGN_VOLUME_MIN_SHARE = 0.95  # share of bars whose volume must match
ALIGN_SKIP_SLOTS = ("15:55",)  # closing-auction bar: Webull folds in the 16:00 cross (price and volume), Alpaca does not
ALIGN_SHIFT_CLOSE_PCT = 0.05   # close match used only to detect a timestamp shift
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
ZONE_SCORE_STRONG = 80             # score = percentile of train raw quality: 80+ = top 20% of zones
ZONE_SCORE_MEDIUM = 50             # under 50 = bottom half
ZONE_SCORE_QUANTILES = 101         # train raw-score quantiles stored with the weights (0..100th)
ZONE_GATE_VALID_START = "2026-05-01"  # Day 3 gate: fit weights before this, check bands from here to TRAIN_END
ZONE_GATE_MIN_TOUCHES = 30         # each band needs this many validation touches to count
ZONE_GATE_MIN_EDGE = 0.10          # 80+ must hold >= 10 points more than <50 ("far more"; random data gave ~8)

# Touch outcome label (Backtest 1): held = moved HOLD_MOVE_ATR away before breaking by BREAK_ATR
HOLD_MOVE_ATR = 0.5
BREAK_ATR = 0.5

# ---------------------------------------------------------------- bounce / trade rules
REJECTION_WICK_PCT = 0.50
REJECTION_CLOSE_ATR = 0.1
FOLLOW_THROUGH_ATR = 0.5
FOLLOW_THROUGH_BARS = 2
MAX_ENTRY_DIST_ATR = 0.5          # chasing: alert-bar close vs the planned entry (not the zone edge)
MAX_ENTRY_FROM_ZONE_ATR = 1.5     # separate cap: planned entry vs the zone edge (rejection candles run ~1 ATR)
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


# ---------------------------------------------------------------- strength / break risk (modules 3-4)
# Factors are scaled to ~0..1 with these caps before weighting.
STRENGTH_CAPS = {
    "reaction_atr": 3.0,        # avg move away after pivots, in ATR
    "tf_count": 3,              # timeframes agreeing
    "pivots": 5,                # pivots in the zone
    "touches": 30,              # bars touching the zone in the loopback
    "volume_ratio": 3.0,        # volume of bars at the level vs average
    "width_atr": 2.0,           # wider = weaker
    "age_bars": 780,            # 10 sessions of 5m bars; older = weaker
}
# Default weights (logit space); Backtest 1 replaces them via models/zone_weights.json.
STRENGTH_WEIGHTS = {
    "bias": -1.0, "reaction_atr": 1.2, "tf_count": 1.0, "pivots": 0.8, "touches": 0.4,
    "round_number": 0.4, "prior_day_level": 0.5, "volume_ratio": 0.6, "role_flip": 0.6,
    "width_atr": -0.8, "age_bars": -0.4,
}
BREAK_CAPS = {
    "recent_tests": 4,          # touches of this zone today before now
    "approach_speed_atr": 3.0,  # distance covered in APPROACH_BARS, in ATR
    "approach_rvol": 3.0,
}
BREAK_WEIGHTS = {
    "bias": -1.5, "recent_tests": 1.2, "approach_speed_atr": 1.0, "approach_straight": 0.8,
    "approach_rvol": 0.6, "regime_against": 1.0, "news_against": 1.5,
}
APPROACH_BARS = 6
ROUND_CONFLUENCE_ATR = 0.25         # round number within this distance of the zone counts
ZONE_WEIGHTS_PATH = "models/zone_weights.json"

# ---------------------------------------------------------------- regime (module 5)
REGIME_SYMBOLS = ("SPY", "QQQ", "SMH")
REGIME_GAP_MIN_DAILY_ATR = 0.15     # gap smaller than this share of daily ATR = no gap
REGIME_CONFIRM_BARS = 2             # same state this many bars = confirmed

# ---------------------------------------------------------------- A+ (module 6)
APLUS_GRADE = 6                     # score >= this = A+
A_GRADE = 4                         # score >= this = A
CATALYST_LOOKBACK_MIN = 120         # ticker headline within this many minutes = catalyst

# ---------------------------------------------------------------- bounce (module 7)
VOLUME_AVG_BARS = 20                # follow-through volume compared with this average

# ---------------------------------------------------------------- trade management
ENTRY_FILL_BARS = 2                 # entry limit stays working this many bars
MIN_T1_R = 1.0                      # skip if T1 is closer than this
DEFAULT_T1_R = 2.0                  # T1 when no opposing zone exists
STALL_BARS = 3                      # stalling candles before a warning
STALL_RANGE_ATR = 0.3
EOD_EXIT = "15:55"                  # flat by this bar's close
MIN_ZONE_SCORE = 50                 # zones below this are watched for break-and-retest only
APLUS_ONLY = False
REQUIRE_REGIME_AGREE = True
NEWS_FILTER = True
TIME_FILTER = None                  # e.g. ("09:45", "15:00") to restrict entries

# ---------------------------------------------------------------- AI layer
AI_PROMPTS_DIR = "ai/prompts"
AI_MAX_TOKENS = 2000               # includes thinking; responses are short JSON
AI_EFFORT = "low"                  # fast, focused judgments inside the 10 s budget
AI_PRICE_IN_PER_MTOK = 2.0         # claude-sonnet-5-5 list prices, for the cost log
AI_PRICE_OUT_PER_MTOK = 10.0
AI_PRICE_TOLERANCE = 0.011         # an AI price must match an allowed level within 1 cent

# ---------------------------------------------------------------- live runtime
LIVE_HISTORY_SESSIONS = 25         # sessions of 5m bars kept in memory (RVOL needs 20)
POLL_DELAY_S = 2                   # poll this long after each 5m boundary
SCHEDULE = {"connect": "04:00", "premarket_plan": "08:30", "cutoff_reminder": "15:45",
            "archive": "16:05", "shutdown": "20:00"}
