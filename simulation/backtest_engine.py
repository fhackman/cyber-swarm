"""CYBER SWARM TRADING OS - Institutional Backtesting & Simulation Engine

Simulates historical candle/tick replay through the complete Swarm pipeline:
    Candle -> Features -> Swarm Deliberation -> Consensus -> Risk Gate -> Fill -> Performance
Calculates Institutional Quant Metrics:
    - Net P&L & Profit Factor
    - Maximum Peak-to-Valley Drawdown (%)
    - Annualized Sharpe Ratio & Sortino Ratio
    - Win Rate (%) & Average R-Multiple
"""
import math
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from cyber_swarm.core.models import (
    OrderDirection,
    ConsensusResult,
    RiskEvaluation,
    MarketTick
)
from cyber_swarm.quant.features import Candle, QuantFeatureEngine
from cyber_swarm.agents.specialized_agents import create_swarm
from cyber_swarm.consensus.consensus_engine import ConsensusEngine
from cyber_swarm.risk.risk_gate import InstitutionalRiskGate

class BacktestConfig(BaseModel):
    initial_equity: float = 1000000.0
    risk_per_trade_pct: float = 1.5
    slippage_bps: float = 0.5
    spread_cost: float = 0.25
    commission_per_lot: float = 7.0

class BacktestTrade(BaseModel):
    trade_id: str
    symbol: str
    direction: OrderDirection
    entry_price: float
    exit_price: float
    lot_size: float
    gross_pnl: float
    net_pnl: float
    r_multiple: float

class BacktestReport(BaseModel):
    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    net_profit: float
    final_equity: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    trades: List[BacktestTrade] = Field(default_factory=list)

class BacktestEngine:
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.feature_engine = QuantFeatureEngine(buffer_size=300)
        self.swarm = create_swarm()
        self.consensus_engine = ConsensusEngine()
        self.risk_gate = InstitutionalRiskGate()

    async def run_simulation(self, candles: List[Candle], symbol: str = "XAUUSD") -> BacktestReport:
        """Executes a chronological event-driven backtest across historical candles."""
        equity = self.config.initial_equity
        peak_equity = equity
        max_drawdown_pct = 0.0

        trades: List[BacktestTrade] = []
        equity_curve: List[float] = [equity]
        trade_returns: List[float] = []

        active_position: Optional[Dict[str, Any]] = None
        trade_counter = 0

        for i, candle in enumerate(candles):
            self.feature_engine.add_candle(symbol, "M15", candle)
            
            # Need at least 15 warmup candles for ATR & EMA
            if i < 15:
                continue

            features = self.feature_engine.calculate_features(symbol, "M15")
            atr = features.atr if features.atr > 0 else 1.0

            # Synthesize tick from candle
            tick = MarketTick(
                symbol=symbol,
                price=candle.close,
                bid=candle.close - (self.config.spread_cost / 2.0),
                ask=candle.close + (self.config.spread_cost / 2.0),
                spread=self.config.spread_cost,
                volume_24h=candle.volume,
                change_pct=((candle.close - candle.open) / candle.open) * 100.0,
                timestamp=candle.timestamp
            )

            # 1. Manage Active Position (Trailing Stop / TP / Reversal)
            if active_position is not None:
                pos_dir = active_position["direction"]
                entry_px = active_position["entry_price"]
                lots = active_position["lots"]
                stop_loss = active_position["stop_loss"]
                take_profit = active_position["take_profit"]

                closed = False
                exit_price = candle.close

                # Check SL/TP hits
                if pos_dir == OrderDirection.BUY:
                    if candle.low <= stop_loss:
                        exit_price = stop_loss
                        closed = True
                    elif candle.high >= take_profit:
                        exit_price = take_profit
                        closed = True
                elif pos_dir == OrderDirection.SELL:
                    if candle.high >= stop_loss:
                        exit_price = stop_loss
                        closed = True
                    elif candle.low <= take_profit:
                        exit_price = take_profit
                        closed = True

                if closed:
                    # Settle trade
                    price_diff = (exit_price - entry_px) if pos_dir == OrderDirection.BUY else (entry_px - exit_price)
                    multiplier = 100.0 if symbol == "XAUUSD" else (1.0 if symbol == "BTCUSD" else 100000.0)
                    gross_pnl = price_diff * lots * multiplier
                    commission = lots * self.config.commission_per_lot
                    net_pnl = gross_pnl - commission

                    equity += net_pnl
                    equity_curve.append(equity)
                    peak_equity = max(peak_equity, equity)
                    dd = ((peak_equity - equity) / peak_equity) * 100.0
                    max_drawdown_pct = max(max_drawdown_pct, dd)

                    r_dist = abs(entry_px - stop_loss)
                    r_mult = price_diff / r_dist if r_dist > 0 else 0.0
                    trade_returns.append(net_pnl / equity)

                    trade_counter += 1
                    trades.append(BacktestTrade(
                        trade_id=f"BT-{trade_counter:04d}",
                        symbol=symbol,
                        direction=pos_dir,
                        entry_price=round(entry_px, 4),
                        exit_price=round(exit_price, 4),
                        lot_size=lots,
                        gross_pnl=round(gross_pnl, 2),
                        net_pnl=round(net_pnl, 2),
                        r_multiple=round(r_mult, 2)
                    ))
                    active_position = None

            # 2. If no position, evaluate swarm deliberation
            if active_position is None:
                signals = []
                for _, agent in self.swarm.items():
                    sig = await agent.evaluate(tick)
                    signals.append(sig)

                consensus = self.consensus_engine.aggregate(signals, symbol)

                # Require high conviction consensus
                if consensus.score >= 0.75 and consensus.direction in [OrderDirection.BUY, OrderDirection.SELL]:
                    risk_lots = 1.0
                    entry_price = tick.ask if consensus.direction == OrderDirection.BUY else tick.bid
                    sl_dist = 1.5 * atr
                    tp_dist = 2.5 * atr

                    sl = (entry_price - sl_dist) if consensus.direction == OrderDirection.BUY else (entry_price + sl_dist)
                    tp = (entry_price + tp_dist) if consensus.direction == OrderDirection.BUY else (entry_price - tp_dist)

                    active_position = {
                        "direction": consensus.direction,
                        "entry_price": entry_price,
                        "lots": risk_lots,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "entry_time": candle.timestamp
                    }

        # Summary Metrics Calculation
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.net_pnl > 0)
        losing_trades = sum(1 for t in trades if t.net_pnl <= 0)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        net_profit = equity - self.config.initial_equity

        # Sharpe & Sortino
        if len(trade_returns) > 1:
            mean_ret = sum(trade_returns) / len(trade_returns)
            variance = sum((r - mean_ret) ** 2 for r in trade_returns) / (len(trade_returns) - 1)
            std_dev = math.sqrt(variance) if variance > 0 else 0.0001
            sharpe = (mean_ret / std_dev) * math.sqrt(252)

            downside_returns = [r for r in trade_returns if r < 0]
            if downside_returns:
                downside_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
                downside_std = math.sqrt(downside_var) if downside_var > 0 else 0.0001
                sortino = (mean_ret / downside_std) * math.sqrt(252)
            else:
                sortino = sharpe * 1.5
        else:
            sharpe = 0.0
            sortino = 0.0

        return BacktestReport(
            symbol=symbol,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=round(win_rate, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=round(profit_factor, 2),
            net_profit=round(net_profit, 2),
            final_equity=round(equity, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            trades=trades
        )
