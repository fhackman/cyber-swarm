"""CYBER SWARM TRADING OS - Pydantic Data Models"""
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

class OrderDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class OrderType(str, Enum):
    MARKET = "MARKET"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

class NetworkStatus(str, Enum):
    ONLINE = "ONLINE"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    RECONCILING = "RECONCILING"
    SYNCED = "SYNCED"

class ReconciliationAction(str, Enum):
    RETAIN = "RETAIN"
    CANCEL = "CANCEL"
    ADOPT_FILLED = "ADOPT_FILLED"

class ConsensusState(str, Enum):
    HOLD = "HOLD"
    WATCH = "WATCH"
    SIGNAL = "SIGNAL"
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    EXTREME_CONSENSUS = "EXTREME_CONSENSUS"

class MarketTick(BaseModel):
    symbol: str
    price: float
    bid: float
    ask: float
    spread: float
    volume_24h: float
    change_pct: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AgentSignal(BaseModel):
    agent_id: str
    symbol: str
    direction: OrderDirection
    confidence: float = Field(ge=0.0, le=1.0)
    weight: float = Field(default=1.0, ge=0.0)
    reliability: float = Field(default=0.95, ge=0.0, le=1.0)
    timeframe: str = "M15"
    evidence: List[str] = Field(default_factory=list)
    raw_aicl: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_version: str = "v1.0.0"

class ConsensusResult(BaseModel):
    cycle_id: int
    symbol: str
    direction: OrderDirection
    score: float = Field(ge=0.0, le=1.0)
    state: ConsensusState
    participating_agents: List[str]
    votes: Dict[str, Dict[str, Any]]
    evidence_chain: List[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class RiskEvaluation(BaseModel):
    approved: bool
    direction: OrderDirection
    symbol: str
    lot_size: float
    estimated_risk_pct: float
    current_drawdown_pct: float
    exposure_pct: float
    reasons: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TradeOrder(BaseModel):
    order_id: str
    cycle_id: Union[int, str] = 0
    symbol: str
    direction: OrderDirection
    order_type: OrderType = OrderType.MARKET
    lot_size: float = 0.10
    target_price: float
    limit_price: Optional[float] = None
    fill_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    take_profit_points: Optional[int] = None
    trailing_distance: Optional[float] = None
    trailing_activation: Optional[float] = None
    slippage_bps: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    decision_trace: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Position(BaseModel):
    position_id: str
    symbol: str
    direction: OrderDirection
    lot_size: float = 0.10
    entry_price: float
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    take_profit_points: Optional[int] = None
    trailing_active: bool = False
    trail_distance: float = 0.0
    trail_activation_delta: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    entry_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ReconciliationRecord(BaseModel):
    order_id: str
    symbol: str
    direction: OrderDirection
    order_type: OrderType
    limit_price: float
    action: ReconciliationAction
    reason: str
    market_price: Optional[float] = None
    consensus_score: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ReconciliationReport(BaseModel):
    reconciliation_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    downtime_seconds: float = 0.0
    total_reviewed: int = 0
    retained_count: int = 0
    cancelled_count: int = 0
    filled_count: int = 0
    records: List[ReconciliationRecord] = Field(default_factory=list)

class PortfolioState(BaseModel):
    net_equity: float
    realized_pnl_mtd: float
    unrealized_pnl: float
    daily_drawdown_pct: float
    max_drawdown_pct: float
    risk_exposure_pct: float
    win_rate_pct: float
    total_trades: int
    volume_24h_usd: float
    auto_trade_enabled: bool = True
    take_profit_enabled: bool = True
    take_profit_points: int = 200
    lot_size: float = 0.10
    fixed_lot_size: float = 0.10
    min_lot_size: float = 0.01
    max_lot_size: float = 5.00
    lot_step: float = 0.01
    lot_presets: List[float] = Field(default_factory=lambda: [0.01, 0.05, 0.10, 0.20, 0.50, 1.00])
    network_status: NetworkStatus = NetworkStatus.ONLINE
    last_reconciliation: Optional[ReconciliationReport] = None
    open_positions: List[Position] = Field(default_factory=list)
    pending_orders: List[TradeOrder] = Field(default_factory=list)
    uptime_pct: float = 99.98
    active_cycle: int = 84209
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TelemetryEvent(BaseModel):
    timestamp: str
    source: str
    event_type: str
    message: str
    payload: Dict[str, Any] = Field(default_factory=dict)
