"""Zone assistant live/replay driver -- alerts only, never places orders.

Wires engine/zone_assistant.py's pure logic to closed 5m bars (live polling
or replayed history, identical code path either way): builds 30m zones the
same way the backtest does (live.zones_live.LiveZoneSource, so live zones
equal backtest zones), scores them with the already-learned weights, steps
the approach/at-zone/reclaim/break alert stage machine per zone, starts a
Day 3-style forward outcome tracker on every "at zone" alert, and sends
alerts via Telegram + logs everything to SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pandas as pd

import config
from alerts import formatter as fmt
from data.base import regular_hours
from engine.features import compute_features
from engine.scoring import load_weights
from engine.settings import EngineSettings
from engine.zone_assistant import AT_ZONE, BROKEN, RECLAIMED, OutcomeTracker, ZoneWatchTracker, hold_rate, labelled_zones
from engine.zones import Zone
from live.zones_live import LiveZoneSource

_SETTINGS = EngineSettings(zone=config.ZONE_ASSISTANT_ZONE_CONFIG, timeframes=(config.ZONE_ASSISTANT_TIMEFRAME,))


@dataclass
class SymbolState:
    symbol: str
    bars: pd.DataFrame
    daily: pd.DataFrame
    zones: LiveZoneSource
    trackers: dict = field(default_factory=dict)    # (bottom, top) -> ZoneWatchTracker
    outcomes: dict = field(default_factory=dict)    # alert id -> (OutcomeTracker, next_zone)
    prev_close: float | None = None


class ZoneAssistantRunner:
    def __init__(self, symbols: list[str], history: dict[str, tuple[pd.DataFrame, pd.DataFrame]], telegram,
                store=None, weights_path: str = config.ZONE_ASSISTANT_WEIGHTS_PATH):
        self.telegram = telegram
        self.store = store
        self.weights = load_weights(weights_path)
        self.state: dict[str, SymbolState] = {}
        for s in symbols:
            bars, daily = history[s]
            zs = LiveZoneSource(s, _SETTINGS, session=config.ZONE_SESSION)
            zs.update(bars, daily)
            self.state[s] = SymbolState(s, bars, daily, zs)

    def _alert(self, symbol: str, kind: str, text: str, now, score: float | None = None) -> int:
        ok = self.telegram.send(text)
        return self.store.alert(symbol, kind, text, ok, now, score) if self.store else -1

    def _log_outcome(self, alert_id: int, symbol: str, now, res: dict):
        if not self.store:
            return
        self.store.zone_outcome(alert_id, symbol, res["outcome"], res["max_move_atr"], res["reached_next"], now)
        self.store.event(SimpleNamespace(time=now, symbol=symbol, kind="zone_outcome",
                                         detail={"alert_id": alert_id, **res}))

    def on_bars(self, now: pd.Timestamp, new: dict[str, pd.DataFrame]):
        """Process newly closed 5m bars (``now`` = the bar close)."""
        for s, b in new.items():
            st = self.state[s]
            st.bars = pd.concat([st.bars, b])
            st.bars = st.bars[~st.bars.index.duplicated(keep="last")].sort_index()
            st.zones.update(st.bars, st.daily)

            reg = regular_hours(st.bars)
            win = reg.iloc[-max(st.zones.window_bars(), 400):]
            feats = compute_features(win, st.daily)
            if not len(feats) or feats.index[-1] + pd.Timedelta("5min") != now:
                continue
            row = feats.iloc[-1]
            atr = row["atr"]
            if not (atr == atr) or atr <= 0:
                continue
            price = float(row["close"])
            prev_close = st.prev_close if st.prev_close is not None else float(feats["close"].iloc[-2]) \
                if len(feats) > 1 else price
            bar = {k: row[k] for k in ("open", "high", "low", "close", "volume")}
            hhmm = now.strftime("%H:%M")

            zones = st.zones(now)
            labelled = labelled_zones(zones, price, atr, win, row, feats["rvol"], self.weights)
            label_by_key = {(lz.zone.bottom, lz.zone.top): lz for lz in labelled}

            # advance outcome trackers started by earlier "at zone" alerts
            done = []
            for alert_id, (ot, _nz) in st.outcomes.items():
                res = ot.step(bar, atr, hhmm)
                if res is not None:
                    self._log_outcome(alert_id, s, now, res)
                    done.append(alert_id)
            for alert_id in done:
                del st.outcomes[alert_id]

            # advance (or start) the alert-stage tracker for every zone currently shown
            for lz in labelled:
                key = (lz.zone.bottom, lz.zone.top)
                tracker = st.trackers.setdefault(key, ZoneWatchTracker(key=key))
                for a in tracker.step(s, lz.label, lz.zone, lz.score, bar, prev_close, atr):
                    text = self._format(a, lz.score)
                    alert_id = self._alert(s, f"zone_{a.stage}", text, now, lz.score)
                    if a.stage == AT_ZONE:
                        next_zone = _next_opposing_zone(zones, lz.zone, tracker.direction)
                        st.outcomes[alert_id] = (OutcomeTracker(tracker.direction, lz.zone, next_zone), next_zone)

            st.prev_close = price

    def _format(self, a, score: float) -> str:
        if a.stage == "approaching":
            return fmt.zone_approaching(a.symbol, a.label, a.zone, score, hold_rate(score))
        if a.stage == AT_ZONE:
            return fmt.zone_at(a.symbol, a.label, a.zone)
        if a.stage == RECLAIMED:
            direction = self.state[a.symbol].trackers[(a.zone.bottom, a.zone.top)].direction or "long"
            return fmt.zone_reclaimed(a.symbol, a.label, a.text_args["close"], a.text_args["wick"], direction)
        if a.stage == BROKEN:
            direction = self.state[a.symbol].trackers[(a.zone.bottom, a.zone.top)].direction or "long"
            return fmt.zone_broken(a.symbol, a.label, a.text_args["close"], direction)
        return fmt.info(f"{a.symbol} {a.stage} {a.label}")


def _next_opposing_zone(zones: list[Zone], zone: Zone, direction: str | None) -> Zone | None:
    """The next zone beyond ``zone`` in the direction price is expected to move if it holds."""
    if direction == "long":
        above = [z for z in zones if z.bottom > zone.top]
        return min(above, key=lambda z: z.bottom) if above else None
    below = [z for z in zones if z.top < zone.bottom]
    return max(below, key=lambda z: z.top) if below else None


def morning_sheet(symbols: list[str], history: dict[str, tuple[pd.DataFrame, pd.DataFrame]], now: pd.Timestamp,
                  weights_path: str = config.ZONE_ASSISTANT_WEIGHTS_PATH) -> dict[str, list]:
    """{symbol: [(label, zone, score, hold_rate), ...]} as of ``now``, for the 9:15 sheet."""
    weights = load_weights(weights_path)
    out = {}
    for s in symbols:
        bars, daily = history[s]
        zs = LiveZoneSource(s, _SETTINGS, session=config.ZONE_SESSION)
        zs.update(bars, daily)
        reg = regular_hours(bars)
        win = reg.iloc[-max(zs.window_bars(), 400):]
        feats = compute_features(win, daily)
        closed = feats[feats.index + pd.Timedelta("5min") <= now]
        if not len(closed):
            out[s] = []
            continue
        row = closed.iloc[-1]
        price, atr = float(row["close"]), row["atr"]
        zones = zs(now)
        labelled = labelled_zones(zones, price, atr, win, row, feats["rvol"], weights)
        out[s] = [(lz.label, lz.zone, lz.score, hold_rate(lz.score)) for lz in labelled]
    return out
