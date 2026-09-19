"""Unit Tests for Multi-Timeframe Candle Aggregator"""
from datetime import datetime, UTC
from cyber_swarm.quant.candle_aggregator import CandleAggregator
from cyber_swarm.core.models import MarketTick

def test_candle_aggregator_in_progress():
    agg = CandleAggregator(timeframes=["M1"])
    tick1 = MarketTick(
        symbol="XAUUSD",
        price=2380.0,
        bid=2379.8,
        ask=2380.2,
        spread=0.4,
        volume_24h=100.0,
        change_pct=0.1,
        timestamp=datetime.fromtimestamp(1700000000, tz=UTC)
    )
    agg.ingest_tick(tick1)

    c = agg.get_forming_candle("XAUUSD", "M1")
    assert c is not None
    assert c.open == 2380.0
    assert c.high == 2380.0
    assert c.low == 2380.0
    assert c.close == 2380.0
    assert c.volume == 1.0

    # Second tick updates high and close
    tick2 = MarketTick(
        symbol="XAUUSD",
        price=2385.0,
        bid=2384.8,
        ask=2385.2,
        spread=0.4,
        volume_24h=100.0,
        change_pct=0.1,
        timestamp=datetime.fromtimestamp(1700000010, tz=UTC)
    )
    agg.ingest_tick(tick2)

    c2 = agg.get_forming_candle("XAUUSD", "M1")
    assert c2 is not None
    assert c2.high == 2385.0
    assert c2.close == 2385.0
    assert c2.volume == 2.0

def test_candle_closure_on_new_bar():
    agg = CandleAggregator(timeframes=["M1"])
    tick1 = MarketTick(
        symbol="BTCUSD",
        price=67000.0,
        bid=66999.0,
        ask=67001.0,
        spread=2.0,
        volume_24h=100.0,
        change_pct=0.1,
        timestamp=datetime.fromtimestamp(1700000000, tz=UTC)
    )
    agg.ingest_tick(tick1)

    # Tick in next minute bar (epoch + 65 seconds)
    tick2 = MarketTick(
        symbol="BTCUSD",
        price=67100.0,
        bid=67099.0,
        ask=67101.0,
        spread=2.0,
        volume_24h=100.0,
        change_pct=0.1,
        timestamp=datetime.fromtimestamp(1700000065, tz=UTC)
    )
    closed = agg.ingest_tick(tick2)
    assert len(closed) == 1
    assert closed[0].close == 67000.0

    # New bar is forming
    forming = agg.get_forming_candle("BTCUSD", "M1")
    assert forming is not None
    assert forming.open == 67100.0
