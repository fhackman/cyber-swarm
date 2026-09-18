"""CYBER SWARM TRADING OS - System Configuration"""
import os
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel, Field

class ExecutionMode(str, Enum):
    LIVE = "LIVE"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    SAFE = "SAFE"

class SystemConfig(BaseModel):
    # Operating Mode & Auto Trade Bot
    mode: ExecutionMode = Field(default=ExecutionMode.PAPER, description="Current operational mode")
    auto_trade_enabled: bool = Field(default=True, description="Master toggle for autonomous trading bot")
    fixed_lot_size: float = Field(default=0.10, description="Current configured order lot size")
    min_lot_size: float = Field(default=0.01, description="Minimum allowable lot size")
    max_lot_size: float = Field(default=5.00, description="Maximum allowable lot size for risk gate")
    lot_step: float = Field(default=0.01, description="Standard lot increment step")
    lot_presets: List[float] = Field(default_factory=lambda: [0.01, 0.05, 0.10, 0.20, 0.50, 1.00], description="Quick UI lot size presets")
    desk_id: str = Field(default="QUANT-DESK-01", description="Trading Desk Identifier")
    version: str = Field(default="v2.4.19-PROD", description="System version")
    
    # Network & Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8420, description="Server port")
    ws_heartbeat_interval: float = Field(default=1.0, description="WebSocket telemetry interval (sec)")
    
    # Tradable Assets
    symbols: List[str] = Field(default_factory=lambda: ["XAUUSD", "BTCUSD", "EURUSD", "USOIL"])
    
    # Auto Trailing Stop Engine
    trailing_stop_enabled: bool = Field(default=True, description="Enable automated dynamic trailing stop ratchet")
    trailing_stop_profiles: Dict[str, Dict[str, float]] = Field(
        default_factory=lambda: {
            "XAUUSD": {"activation_delta": 4.0, "trail_distance": 8.0, "step": 0.5},
            "BTCUSD": {"activation_delta": 100.0, "trail_distance": 200.0, "step": 10.0},
            "EURUSD": {"activation_delta": 0.0006, "trail_distance": 0.0010, "step": 0.0001},
            "USOIL": {"activation_delta": 0.30, "trail_distance": 0.50, "step": 0.05}
        },
        description="Per-asset trailing stop calibration"
    )
    limit_order_offset_pct: float = Field(default=0.0015, description="Offset for placing pending limit orders (0.15% from market)")
    
    # Auto Take Profit Engine (100 - 300 points)
    take_profit_enabled: bool = Field(default=True, description="Enable automated take profit target")
    take_profit_points: int = Field(default=200, description="Default take profit target in points (100-300 points)")
    take_profit_points_min: int = Field(default=100, description="Minimum allowable take profit points")
    take_profit_points_max: int = Field(default=300, description="Maximum allowable take profit points")
    point_sizes: Dict[str, float] = Field(
        default_factory=lambda: {
            "XAUUSD": 0.01,     # 100 pt = $1.00, 200 pt = $2.00, 300 pt = $3.00
            "BTCUSD": 1.0,      # 100 pt = $100.00, 200 pt = $200.00, 300 pt = $300.00
            "EURUSD": 0.00001,  # 100 pt = 10 pips (0.00100), 200 pt = 20 pips, 300 pt = 30 pips
            "USOIL": 0.01,      # 100 pt = $1.00, 200 pt = $2.00, 300 pt = $3.00
            "USOUSD": 0.01      # MT5 Eightcap Oil mapping
        },
        description="Value of 1 point in price units per asset"
    )
    
    # Institutional Risk Gate Parameters
    initial_equity: float = Field(default=1482920.45, description="Initial base portfolio equity USD")
    max_risk_per_trade_pct: float = Field(default=10.0, description="Hard cap on risk per single trade (%)")
    max_drawdown_limit_pct: float = Field(default=5.0, description="Daily maximum drawdown hard stop (%)")
    max_total_exposure_pct: float = Field(default=40.0, description="Maximum aggregated portfolio exposure (%)")
    max_open_positions: int = Field(default=8, description="Maximum concurrent active open positions")
    max_stale_data_latency_ms: int = Field(default=2000, description="Max acceptable feed latency before fail-closed (ms)")
    
    # Consensus Thresholds
    consensus_hold_max: float = Field(default=0.55, description="Under 55% -> HOLD")
    consensus_watch_max: float = Field(default=0.70, description="55%-70% -> WATCH")
    consensus_signal_min: float = Field(default=0.70, description="70%-80% -> SIGNAL")
    consensus_high_conviction_min: float = Field(default=0.80, description="80%-90% -> HIGH CONVICTION")
    consensus_extreme_min: float = Field(default=0.90, description=">90% -> EXTREME CONSENSUS")
    
    # MT5 Integration
    mt5_request_file: str = Field(default="request.txt", description="File used for bridge communication")
    mt5_data_file: str = Field(default="candles.csv", description="File containing tick/candle data")

    # Network Reconnection & Pending Order Reconciliation
    network_reconciliation_enabled: bool = Field(default=True, description="Enable automatic order reconciliation upon network reconnection")
    network_timeout_seconds: float = Field(default=3.0, description="Timeout threshold before flagging network disconnection")
    max_pending_order_ttl_seconds: int = Field(default=3600, description="Max time-to-live for pending limit orders (seconds)")
    reconnect_price_drift_max_pct: float = Field(default=0.005, description="Max acceptable price drift (0.5%) before order is marked stale/inverted")

# Global singleton configuration
config = SystemConfig()
