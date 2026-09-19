"""CYBER SWARM TRADING OS - Real-Time Candle Aggregator

Aggregates incoming tick streams into multi-timeframe OHLCV candles (M1, M5, M15, H1),
tracks bar completion, and dispatches updates to the Quant Feature Engine.
"""
import logging
from datetime import datetime, UTC
from typing import Any
from collections.abc import Callable
from cyber_swarm.core.models import MarketTick
from cyber_swarm.quant.features import Candle, feature_engine

logger = logging.getLogger("cyber_swarm.candle_aggregator")

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600
}

class CandleAggregator:
    def __init__(self, timeframes: list[str] | None = None):
        self.timeframes = timeframes or ["M1", "M5", "M15", "H1"]
        # In-progress candles: { "XAUUSD_M15": Candle }
        self._forming_candles: dict[str, Candle] = {}
        # Bar start timestamps: { "XAUUSD_M15": int_epoch }
        self._bar_starts: dict[str, int] = {}
        # Callbacks for closed candles: list of callable(symbol, timeframe, candle)
        self.on_candle_close: list[Callable[[str, str, Candle], Any]] = []

    def _get_bar_bucket(self, ts_epoch: float, interval_sec: int) -> int:
        return int(ts_epoch // interval_sec) * interval_sec

    def ingest_tick(self, tick: MarketTick) -> list[Candle]:
        """Processes an incoming tick across all configured timeframes.
        Returns a list of completed (closed) candles if any bar ended.
        """
        closed_candles = []
        tick_time = tick.timestamp.timestamp()

        for tf in self.timeframes:
            interval_sec = TIMEFRAME_SECONDS[tf]
            bar_bucket = self._get_bar_bucket(tick_time, interval_sec)
            key = f"{tick.symbol.upper()}_{tf.upper()}"

            if key not in self._bar_starts:
                # First tick in bar
                self._bar_starts[key] = bar_bucket
                self._forming_candles[key] = Candle(
                    timestamp=datetime.fromtimestamp(bar_bucket, tz=UTC),
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                    volume=1.0
                )
            elif bar_bucket > self._bar_starts[key]:
                # Current bar closed, new bar begins
                completed = self._forming_candles[key]
                closed_candles.append(completed)

                # Push into feature engine
                feature_engine.add_candle(tick.symbol, tf, completed)

                # Notify listeners
                for cb in self.on_candle_close:
                    try:
                        cb(tick.symbol, tf, completed)
                    except Exception as e:
                        logger.warning(
                            f"Error executing candle close callback {cb} for {tick.symbol} {tf}: {e}",
                            exc_info=True
                        )

                # Initialize new forming bar
                self._bar_starts[key] = bar_bucket
                self._forming_candles[key] = Candle(
                    timestamp=datetime.fromtimestamp(bar_bucket, tz=UTC),
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                    volume=1.0
                )
            else:
                # Update current forming bar
                c = self._forming_candles[key]
                c.high = max(c.high, tick.price)
                c.low = min(c.low, tick.price)
                c.close = tick.price
                c.volume += 1.0

        return closed_candles

    def get_forming_candle(self, symbol: str, timeframe: str = "M15") -> Candle | None:
        key = f"{symbol.upper()}_{timeframe.upper()}"
        return self._forming_candles.get(key)

# Global singleton aggregator
candle_aggregator = CandleAggregator()
