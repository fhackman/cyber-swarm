"""Unit Tests for Backtest Simulation Engine"""
import pytest
from datetime import datetime, timezone, timedelta
from cyber_swarm.simulation.backtest_engine import BacktestEngine, BacktestConfig
from cyber_swarm.quant.features import Candle

@pytest.mark.asyncio
async def test_backtest_simulation_run():
    engine = BacktestEngine(BacktestConfig(initial_equity=500000.0))
    
    # Generate 50 synthetic trending candles
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = []
    price = 2350.0
    for i in range(50):
        # Slightly increasing volatility
        price += (1.5 if i % 2 == 0 else -0.5)
        c = Candle(
            timestamp=base_time + timedelta(minutes=15 * i),
            open=price - 0.5,
            high=price + 2.0,
            low=price - 1.5,
            close=price,
            volume=500.0
        )
        candles.append(c)

    report = await engine.run_simulation(candles, symbol="XAUUSD")
    assert report.symbol == "XAUUSD"
    assert report.final_equity > 0.0
    assert report.max_drawdown_pct >= 0.0
    assert isinstance(report.win_rate_pct, float)
    assert isinstance(report.sharpe_ratio, float)
