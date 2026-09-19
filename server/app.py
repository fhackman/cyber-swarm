"""CYBER SWARM TRADING OS - FastAPI Telemetry Server"""
import asyncio
import os
import math
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from cyber_swarm.core.config import config, ExecutionMode
from cyber_swarm.core.models import MarketTick, OrderDirection, OrderType, ConsensusState, OrderStatus, NetworkStatus, ReconciliationReport
from cyber_swarm.agents.specialized_agents import create_swarm
from cyber_swarm.consensus.consensus_engine import ConsensusEngine
from cyber_swarm.risk.risk_gate import InstitutionalRiskGate
from cyber_swarm.execution.router import ExecutionRouter
from cyber_swarm.execution.mt5_connector import MT5Connector
from cyber_swarm.audit.ledger import ledger
from cyber_swarm.quant.candle_aggregator import candle_aggregator
from cyber_swarm.quant.features import Candle
from cyber_swarm.simulation.backtest_engine import BacktestEngine, BacktestConfig, BacktestReport
from cyber_swarm.audit.persistence import audit_db
import logging

logger = logging.getLogger("cyber_swarm.server")

# Static path
STATIC_DIR = Path(__file__).parent / "static"

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        payload = jsonable_encoder(message)
        for connection in list(self.active_connections):
            try:
                await connection.send_json(payload)
            except Exception as e:
                logger.debug(f"Disconnecting stale websocket client: {e}")
                self.active_connections.discard(connection)

manager = ConnectionManager()

# Instantiate core engines
swarm = create_swarm()
consensus_engine = ConsensusEngine()
risk_gate = InstitutionalRiskGate()
router = ExecutionRouter()
mt5_conn = MT5Connector()

current_consensus = None
current_risk_eval = None
current_ticks: Dict[str, MarketTick] = {}

async def swarm_background_loop():
    """Continuous autonomous deliberation cycle broadcasting real-time telemetry."""
    global current_consensus, current_risk_eval
    symbols = config.symbols
    cycle_idx = 0
    while True:
        try:
            sym = symbols[cycle_idx % len(symbols)]
            cycle_idx += 1

            # 0. Check MT5 live connection and handle reconnection reconciliation
            mt5_conn.check_live_connection()
            if config.network_reconciliation_enabled and (mt5_conn.reconnected_event or router.portfolio.network_status == NetworkStatus.RECONCILING):
                logger.info(f"Reconnection event detected! Reconciling pending orders (downtime: {mt5_conn.downtime_duration_seconds}s)...")
                rec_report = router.reconcile_pending_orders(
                    current_ticks=current_ticks,
                    current_consensus={sym: current_consensus} if current_consensus else None,
                    downtime_seconds=mt5_conn.downtime_duration_seconds
                )
                mt5_conn.reconnected_event = False
                mt5_conn.network_status = NetworkStatus.SYNCED
                router.portfolio.network_status = NetworkStatus.SYNCED
                ev = ledger.record_event(
                    source="VESKA",
                    event_type="NETWORK_RECONNECTED_RECONCILED",
                    message=f"Network restored after {rec_report.downtime_seconds}s: Reviewed {rec_report.total_reviewed}, Cancelled {rec_report.cancelled_count}, Adopted {rec_report.filled_count}, Retained {rec_report.retained_count}",
                    payload=rec_report.model_dump(mode="json")
                )
                audit_db.persist_record(ev)
            elif router.portfolio.network_status != NetworkStatus.RECONCILING:
                router.portfolio.network_status = mt5_conn.network_status

            # 1. Fetch Tick (Pure real MT5 tick if online, else realistic simulated jitter)
            tick = await mt5_conn.fetch_tick(sym)
            if not mt5_conn.connected:
                jitter_scales = {
                    "XAUUSD": 0.20,
                    "BTCUSD": 5.0,
                    "EURUSD": 0.0002,
                    "USOIL": 0.10
                }
                scale = jitter_scales.get(sym, 0.05)
                jitter = (random.random() - 0.5) * scale
                decimals = 4 if sym == "EURUSD" else 2
                tick.price = round(tick.price + jitter, decimals)
                tick.bid = round(tick.price - tick.spread / 2.0, decimals)
                tick.ask = round(tick.price + tick.spread / 2.0, decimals)
            current_ticks[sym] = tick

            # Real Account Synchronization
            acc_info = mt5_conn.get_real_account_info()
            if acc_info.get("connected"):
                router.portfolio.net_equity = acc_info["equity"]
                live_pos = mt5_conn.fetch_live_positions()
                if live_pos:
                    router.portfolio.open_positions = live_pos
                    router.active_positions = {p.position_id: p for p in live_pos}
                if config.take_profit_enabled:
                    mt5_conn.sync_pending_orders_tp(config.take_profit_points)

            # Feed tick to Real-Time Candle Aggregator
            candle_aggregator.ingest_tick(tick)

            # Check pending limit orders against incoming tick
            filled_limits = router.check_pending_orders(tick)
            for fl_order in filled_limits:
                ev = ledger.record_event(
                    source="VESKA",
                    event_type="ORDER_FILLED",
                    message=f"Filled {fl_order.order_type.value} 0.10 lot {sym} @ {fl_order.fill_price}",
                    payload={"order_id": fl_order.order_id, "symbol": sym, "type": fl_order.order_type.value}
                )
                audit_db.persist_order(fl_order)
                audit_db.persist_record(ev)

            # Apply Auto Take Profit Engine (100 - 300 points)
            tp_msgs = router.apply_take_profit(tick)
            for tp_msg in tp_msgs:
                ev = ledger.record_event(
                    source="VESKA",
                    event_type="TAKE_PROFIT_TRIGGERED",
                    message=tp_msg,
                    payload={"symbol": sym}
                )
                audit_db.persist_record(ev)

            # Apply Auto Trailing Stop Engine
            trailing_msgs = router.apply_trailing_stop(tick)
            for t_msg in trailing_msgs:
                ev = ledger.record_event(
                    source="MARIN",
                    event_type="TRAILING_STOP",
                    message=t_msg,
                    payload={"symbol": sym}
                )
                audit_db.persist_record(ev)

            # Update open positions mark-to-market and manage SL/TP rotation
            closed_msgs = router.update_positions(tick)
            for c_msg in closed_msgs:
                ev = ledger.record_event(
                    source="MARIN",
                    event_type="POSITION_SETTLED",
                    message=c_msg,
                    payload={"symbol": sym}
                )
                audit_db.persist_record(ev)

            # 2. Run Swarm Deliberation
            signals = []
            for agent_id, agent in swarm.items():
                sig = await agent.evaluate(tick)
                signals.append(sig)

            # 3. Consensus Engine
            current_consensus = consensus_engine.aggregate(signals, sym)

            # 4. Risk Gate (Enforces Fixed 0.10 lot and Auto Trade Toggle)
            current_risk_eval = risk_gate.evaluate_pre_trade(
                consensus=current_consensus,
                tick=tick,
                portfolio=router.portfolio,
                lot_size=config.fixed_lot_size
            )

            # 5. Autonomous Trade Bot Execution if approved (Blocked in SAFE and BACKTEST modes)
            if current_risk_eval.approved and config.auto_trade_enabled and config.mode not in (ExecutionMode.SAFE, ExecutionMode.BACKTEST):
                # High Conviction (>= 85%): Direct Market Execution (0.10 lot)
                if current_consensus.score >= 0.85:
                    order = await router.execute_order(current_risk_eval, current_consensus, tick)
                    ev = ledger.record_event(
                        source="VESKA",
                        event_type="ORDER_FILLED",
                        message=f"Filled {order.direction.value} {order.lot_size} lot {sym} @ {order.fill_price}",
                        payload={"order_id": order.order_id, "symbol": sym, "score": current_consensus.score}
                    )
                    audit_db.persist_order(order)
                    audit_db.persist_record(ev)

                # Standard Signal (70% - 85%): Auto Limit Order Entry (BUY_LIMIT / SELL_LIMIT @ 0.10 lot)
                elif current_consensus.score >= 0.70:
                    existing_pending = [o for o in router.pending_orders.values() if o.symbol == sym and o.status == OrderStatus.PENDING]
                    if len(existing_pending) == 0:
                        decimals = 4 if sym == "EURUSD" else 2
                        if current_risk_eval.direction == OrderDirection.BUY:
                            lmt_price = round(tick.price * (1.0 - config.limit_order_offset_pct), decimals)
                            order_type = OrderType.BUY_LIMIT
                        else:
                            lmt_price = round(tick.price * (1.0 + config.limit_order_offset_pct), decimals)
                            order_type = OrderType.SELL_LIMIT

                        order = router.create_pending_limit_order(
                            symbol=sym,
                            direction=current_risk_eval.direction,
                            order_type=order_type,
                            limit_price=lmt_price,
                            cycle_id=current_consensus.cycle_id
                        )
                        ev = ledger.record_event(
                            source="VESKA",
                            event_type="LIMIT_ORDER_PLACED",
                            message=f"Placed {order.order_type.value} {order.lot_size:.2f} lot {sym} @ {lmt_price}",
                            payload={"order_id": order.order_id, "symbol": sym, "score": current_consensus.score}
                        )
                        audit_db.persist_order(order)
                        audit_db.persist_record(ev)

                        # Sync with MT5 terminal if online
                        if mt5_conn.connected:
                            mt5_conn.send_pending_limit_order(sym, order.direction, lmt_price, lot_size=order.lot_size, tp=order.take_profit)

            # Ensure portfolio open positions reflect real MT5 terminal
            if acc_info.get("connected"):
                live_pos = mt5_conn.fetch_live_positions()
                if live_pos:
                    router.portfolio.open_positions = live_pos
                    router.active_positions = {p.position_id: p for p in live_pos}

            # 6. Broadcast Telemetry Snapshot over WebSocket
            telemetry_payload = {
                "type": "TELEMETRY_UPDATE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "mode": config.mode.value,
                    "auto_trade_enabled": config.auto_trade_enabled,
                    "fixed_lot_size": config.fixed_lot_size,
                    "lot_size": config.fixed_lot_size,
                    "min_lot_size": config.min_lot_size,
                    "max_lot_size": config.max_lot_size,
                    "lot_step": config.lot_step,
                    "lot_presets": config.lot_presets,
                    "trailing_stop_enabled": config.trailing_stop_enabled,
                    "take_profit_enabled": config.take_profit_enabled,
                    "take_profit_points": config.take_profit_points,
                    "desk_id": f"{acc_info['name']} ({acc_info['login']})" if acc_info.get("connected") else config.desk_id,
                    "version": config.version,
                    "killswitch": risk_gate.killswitch_active,
                    "mt5_connected": acc_info.get("connected", False),
                    "mt5_server": acc_info.get("server", "Demo"),
                    "mt5_ping_ms": acc_info.get("ping_ms", 4.2),
                    "account_equity": acc_info.get("equity", router.portfolio.net_equity),
                    "account_balance": acc_info.get("balance", router.portfolio.net_equity),
                    "network_status": router.portfolio.network_status.value if hasattr(router.portfolio.network_status, "value") else str(router.portfolio.network_status),
                    "downtime_seconds": mt5_conn.downtime_duration_seconds,
                    "last_reconciliation": router.portfolio.last_reconciliation.model_dump(mode="json") if router.portfolio.last_reconciliation else None
                },
                "portfolio": router.portfolio.model_dump(mode="json"),
                "ticks": {k: v.model_dump() for k, v in current_ticks.items()},
                "pending_orders": [o.model_dump(mode="json") for o in router.pending_orders.values() if o.status == OrderStatus.PENDING],
                "last_reconciliation": router.portfolio.last_reconciliation.model_dump(mode="json") if router.portfolio.last_reconciliation else None,
                "agents": {k: v.get_telemetry() for k, v in swarm.items()},
                "consensus": current_consensus.model_dump() if current_consensus else None,
                "risk_gate": current_risk_eval.model_dump() if current_risk_eval else None,
                "recent_audit": [r.model_dump() for r in ledger.get_recent(15)],
                "recent_orders": [o.model_dump() for o in router.get_recent_orders(10)]
            }
            await manager.broadcast(telemetry_payload)

        except Exception as e:
            logger.error(f"Error in swarm background loop: {e}", exc_info=True)
            await asyncio.sleep(1.0)
            continue

        await asyncio.sleep(config.ws_heartbeat_interval)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize ticks
    for s in config.symbols:
        current_ticks[s] = await mt5_conn.fetch_tick(s)
    task = asyncio.create_task(swarm_background_loop())
    yield
    task.cancel()

app = FastAPI(title="CYBER SWARM TRADING OS", version=config.version, lifespan=lifespan)

# REST Endpoints
@app.get("/api/state")
async def get_state():
    acc_info = mt5_conn.get_real_account_info()
    return {
        "config": {
            "mode": config.mode.value,
            "auto_trade_enabled": config.auto_trade_enabled,
            "fixed_lot_size": config.fixed_lot_size,
            "lot_size": config.fixed_lot_size,
            "min_lot_size": config.min_lot_size,
            "max_lot_size": config.max_lot_size,
            "lot_step": config.lot_step,
            "lot_presets": config.lot_presets,
            "trailing_stop_enabled": config.trailing_stop_enabled,
            "take_profit_enabled": config.take_profit_enabled,
            "take_profit_points": config.take_profit_points,
            "desk_id": f"{acc_info['name']} ({acc_info['login']})" if acc_info.get("connected") else config.desk_id,
            "version": config.version,
            "killswitch": risk_gate.killswitch_active,
            "mt5_connected": acc_info.get("connected", False),
            "mt5_server": acc_info.get("server", "Demo"),
            "mt5_ping_ms": acc_info.get("ping_ms", 4.2),
            "account_equity": acc_info.get("equity", router.portfolio.net_equity),
            "account_balance": acc_info.get("balance", router.portfolio.net_equity),
            "network_status": router.portfolio.network_status.value if hasattr(router.portfolio.network_status, "value") else str(router.portfolio.network_status),
            "downtime_seconds": mt5_conn.downtime_duration_seconds,
            "last_reconciliation": router.portfolio.last_reconciliation.model_dump(mode="json") if router.portfolio.last_reconciliation else None
        },
        "portfolio": router.portfolio.model_dump(mode="json"),
        "ticks": {k: v.model_dump(mode="json") for k, v in current_ticks.items()},
        "pending_orders": [o.model_dump(mode="json") for o in router.pending_orders.values() if o.status == OrderStatus.PENDING],
        "last_reconciliation": router.portfolio.last_reconciliation.model_dump(mode="json") if router.portfolio.last_reconciliation else None,
        "agents": {k: v.get_telemetry() for k, v in swarm.items()},
        "consensus": current_consensus.model_dump(mode="json") if current_consensus else None,
        "risk_gate": current_risk_eval.model_dump(mode="json") if current_risk_eval else None,
        "recent_audit": [r.model_dump(mode="json") for r in ledger.get_recent(25)],
        "recent_orders": [o.model_dump(mode="json") for o in router.get_recent_orders(10)]
    }

class KillswitchReq(BaseModel):
    action: str  # "trigger" or "reset"
    reason: str = "Operator manual request"

@app.post("/api/killswitch")
async def set_killswitch(req: KillswitchReq):
    if req.action.lower() == "trigger":
        risk_gate.trigger_emergency_stop(req.reason)
        ledger.record_event("OPERATOR", "EMERGENCY_HALT", f"Killswitch triggered: {req.reason}")
    else:
        risk_gate.reset_emergency_stop()
        ledger.record_event("OPERATOR", "HALT_RESET", "Killswitch cleared. System resumed.")
    return {"killswitch_active": risk_gate.killswitch_active}

class ModeReq(BaseModel):
    mode: ExecutionMode

@app.post("/api/mode")
async def set_mode(req: ModeReq):
    config.mode = req.mode
    msg = f"Execution mode changed to {req.mode.value}"
    ev = ledger.record_event("OPERATOR", "MODE_CHANGE", msg)
    audit_db.persist_record(ev)

    # Immediately broadcast mode change to all active WebSocket clients
    await manager.broadcast({
        "type": "MODE_CHANGE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": config.mode.value,
        "message": msg,
        "config": {
            "mode": config.mode.value,
            "auto_trade_enabled": config.auto_trade_enabled,
            "fixed_lot_size": config.fixed_lot_size,
            "lot_size": config.fixed_lot_size,
            "trailing_stop_enabled": config.trailing_stop_enabled,
            "take_profit_enabled": config.take_profit_enabled,
            "take_profit_points": config.take_profit_points,
            "killswitch": risk_gate.killswitch_active,
            "mt5_connected": mt5_conn.connected
        }
    })

    return {
        "status": "SUCCESS",
        "mode": config.mode.value,
        "message": msg,
        "mt5_connected": mt5_conn.connected
    }

class AutoTradeReq(BaseModel):
    enabled: bool

@app.get("/api/autotrade")
async def get_autotrade():
    return {
        "auto_trade_enabled": config.auto_trade_enabled,
        "fixed_lot_size": config.fixed_lot_size,
        "lot_size": config.fixed_lot_size,
        "min_lot_size": config.min_lot_size,
        "max_lot_size": config.max_lot_size,
        "lot_step": config.lot_step,
        "lot_presets": config.lot_presets,
        "trailing_stop_enabled": config.trailing_stop_enabled,
        "take_profit_enabled": config.take_profit_enabled,
        "take_profit_points": config.take_profit_points
    }

@app.post("/api/autotrade")
async def set_autotrade(req: AutoTradeReq):
    config.auto_trade_enabled = req.enabled
    router.portfolio.auto_trade_enabled = req.enabled
    status_str = "ENABLED" if req.enabled else "DISABLED"
    ledger.record_event("OPERATOR", "AUTOTRADE_TOGGLE", f"Auto Trade Bot {status_str}")
    return {"auto_trade_enabled": config.auto_trade_enabled}

class LotSizeReq(BaseModel):
    lot_size: float

@app.get("/api/config/lot-size")
async def get_lot_size():
    return {
        "lot_size": config.fixed_lot_size,
        "min_lot_size": config.min_lot_size,
        "max_lot_size": config.max_lot_size,
        "lot_step": config.lot_step,
        "lot_presets": config.lot_presets
    }

@app.post("/api/config/lot-size")
async def set_lot_size(req: LotSizeReq):
    if req.lot_size < config.min_lot_size or req.lot_size > config.max_lot_size:
        raise HTTPException(
            status_code=400,
            detail=f"Lot size must be between {config.min_lot_size} and {config.max_lot_size}"
        )
    val = round(req.lot_size, 2)
    old_val = config.fixed_lot_size
    config.fixed_lot_size = val
    router.portfolio.lot_size = val
    router.portfolio.fixed_lot_size = val
    ev = ledger.record_event(
        source="OPERATOR",
        event_type="LOT_SIZE_ADJUSTED",
        message=f"Lot size adjusted from {old_val:.2f} to {val:.2f}",
        payload={"old_lot_size": old_val, "new_lot_size": val}
    )
    audit_db.persist_record(ev)
    return {
        "status": "SUCCESS",
        "lot_size": config.fixed_lot_size,
        "min_lot_size": config.min_lot_size,
        "max_lot_size": config.max_lot_size,
        "lot_step": config.lot_step,
        "lot_presets": config.lot_presets
    }

class TrailingStopReq(BaseModel):
    enabled: bool

@app.post("/api/trailing-stop/toggle")
async def set_trailing_stop(req: TrailingStopReq):
    config.trailing_stop_enabled = req.enabled
    status_str = "ENABLED" if req.enabled else "DISABLED"
    ledger.record_event("OPERATOR", "TRAILING_STOP_TOGGLE", f"Auto Trailing Stop {status_str}")
    return {"trailing_stop_enabled": config.trailing_stop_enabled}

class TakeProfitReq(BaseModel):
    enabled: Optional[bool] = None
    points: Optional[int] = None

@app.get("/api/takeprofit")
async def get_take_profit():
    return {
        "take_profit_enabled": config.take_profit_enabled,
        "take_profit_points": config.take_profit_points,
        "take_profit_points_min": config.take_profit_points_min,
        "take_profit_points_max": config.take_profit_points_max
    }

@app.post("/api/takeprofit")
async def set_take_profit(req: TakeProfitReq):
    if req.points is not None:
        if req.points < config.take_profit_points_min or req.points > config.take_profit_points_max:
            raise HTTPException(
                status_code=400,
                detail=f"Take profit points must be between {config.take_profit_points_min} and {config.take_profit_points_max}"
            )
        config.take_profit_points = req.points
        router.portfolio.take_profit_points = req.points
    if req.enabled is not None:
        config.take_profit_enabled = req.enabled
        router.portfolio.take_profit_enabled = req.enabled

    status_str = "ENABLED" if config.take_profit_enabled else "DISABLED"
    ledger.record_event("OPERATOR", "TAKE_PROFIT_CONFIG", f"Auto Take Profit {status_str} ({config.take_profit_points} pt)")
    return {
        "take_profit_enabled": config.take_profit_enabled,
        "take_profit_points": config.take_profit_points
    }

class LimitOrderReq(BaseModel):
    symbol: str
    direction: OrderDirection
    order_type: OrderType
    limit_price: float
    take_profit_points: Optional[int] = None
    lot_size: Optional[float] = None

@app.post("/api/orders/limit")
async def place_limit_order(req: LimitOrderReq):
    if config.mode == ExecutionMode.SAFE:
        raise HTTPException(
            status_code=403,
            detail="SAFE MODE ACTIVE: Order placement is strictly prohibited. Fail-closed invariants enforced."
        )
    if config.mode == ExecutionMode.BACKTEST:
        raise HTTPException(
            status_code=400,
            detail="BACKTEST MODE ACTIVE: Direct live limit order placement is disabled. Use the Backtest Cockpit to run historical simulations."
        )
    if req.order_type not in (OrderType.BUY_LIMIT, OrderType.SELL_LIMIT):
        raise HTTPException(status_code=400, detail="Invalid order type for limit order")
    if req.take_profit_points is not None:
        if req.take_profit_points < config.take_profit_points_min or req.take_profit_points > config.take_profit_points_max:
            raise HTTPException(
                status_code=400,
                detail=f"Take profit points must be between {config.take_profit_points_min} and {config.take_profit_points_max}"
            )
    target_lot = req.lot_size if req.lot_size is not None else config.fixed_lot_size
    if target_lot < config.min_lot_size or target_lot > config.max_lot_size:
        raise HTTPException(
            status_code=400,
            detail=f"Lot size must be between {config.min_lot_size} and {config.max_lot_size}"
        )
    order = router.create_pending_limit_order(
        symbol=req.symbol,
        direction=req.direction,
        order_type=req.order_type,
        limit_price=req.limit_price,
        cycle_id=f"manual_{datetime.now(timezone.utc).strftime('%H%M%S')}",
        take_profit_points=req.take_profit_points,
        lot_size=target_lot
    )
    ev = ledger.record_event(
        source="OPERATOR",
        event_type="LIMIT_ORDER_PLACED",
        message=f"Manual limit order placed: {order.order_type.value} {order.lot_size:.2f} lot {order.symbol} @ {order.limit_price}",
        payload={"order_id": order.order_id, "symbol": order.symbol, "lot_size": order.lot_size, "limit_price": order.limit_price, "take_profit": order.take_profit}
    )
    audit_db.persist_order(order)
    audit_db.persist_record(ev)
    if mt5_conn.connected:
        mt5_conn.send_pending_limit_order(order.symbol, order.direction, order.limit_price, lot_size=order.lot_size, tp=order.take_profit)
    return {"status": "SUCCESS", "order": order.model_dump(mode="json")}

@app.delete("/api/orders/pending/{order_id}")
async def cancel_pending_order(order_id: str):
    order = router.cancel_pending_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pending order not found")
    ledger.record_event("OPERATOR", "LIMIT_ORDER_CANCELLED", f"Cancelled limit order {order_id} ({order.symbol})")
    return {"status": "CANCELLED", "order_id": order_id}

@app.get("/api/network/status")
async def get_network_status():
    """Returns real-time network connectivity, MT5 socket health, downtime, and last reconciliation report."""
    acc_info = mt5_conn.get_real_account_info()
    return {
        "connected": mt5_conn.connected,
        "network_status": router.portfolio.network_status.value if hasattr(router.portfolio.network_status, "value") else str(router.portfolio.network_status),
        "ping_ms": mt5_conn.ping_ms,
        "downtime_seconds": mt5_conn.downtime_duration_seconds,
        "server": acc_info.get("server", "Demo"),
        "last_reconciliation": router.portfolio.last_reconciliation.model_dump(mode="json") if router.portfolio.last_reconciliation else None
    }

@app.post("/api/network/reconcile")
async def trigger_manual_reconcile():
    """Manually triggers full post-reconnection reconciliation across all active pending limit orders."""
    downtime = mt5_conn.downtime_duration_seconds
    rec_report = router.reconcile_pending_orders(
        current_ticks=current_ticks,
        current_consensus={current_consensus.symbol: current_consensus} if current_consensus else None,
        downtime_seconds=downtime
    )
    router.portfolio.network_status = NetworkStatus.SYNCED
    mt5_conn.network_status = NetworkStatus.SYNCED
    ev = ledger.record_event(
        source="OPERATOR",
        event_type="MANUAL_RECONCILIATION_TRIGGERED",
        message=f"Manual order reconciliation: Reviewed {rec_report.total_reviewed}, Retained {rec_report.retained_count}, Cancelled {rec_report.cancelled_count}, Adopted {rec_report.filled_count}",
        payload=rec_report.model_dump(mode="json")
    )
    audit_db.persist_record(ev)
    return {
        "status": "SUCCESS",
        "report": rec_report.model_dump(mode="json")
    }

@app.post("/api/mt5/sync-tp")
async def trigger_mt5_tp_sync():
    """Manually triggers immediate Take Profit synchronization across all open positions and pending orders on MT5."""
    if not mt5_conn.connected:
        return {"status": "SKIPPED", "message": "MT5 terminal not connected", "open_positions_synced": 0, "pending_orders_synced": 0}
    
    pos_count = mt5_conn.sync_open_positions_tp(config.take_profit_points)
    ord_count = mt5_conn.sync_pending_orders_tp(config.take_profit_points)
    
    ev = ledger.record_event(
        source="VESKA",
        event_type="MT5_TP_SYNCED",
        message=f"Synced broker Take Profit on MT5: {pos_count} open positions, {ord_count} pending orders",
        payload={"open_positions_synced": pos_count, "pending_orders_synced": ord_count, "tp_points": config.take_profit_points}
    )
    audit_db.persist_record(ev)
    return {
        "status": "SUCCESS",
        "open_positions_synced": pos_count,
        "pending_orders_synced": ord_count,
        "take_profit_points": config.take_profit_points
    }

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        acc_info = mt5_conn.get_real_account_info()
        if acc_info.get("connected"):
            live_pos = mt5_conn.fetch_live_positions()
            if live_pos:
                router.portfolio.open_positions = live_pos
                router.active_positions = {p.position_id: p for p in live_pos}
        initial_state = {
            "type": "INITIAL_SNAPSHOT",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "mode": config.mode.value,
                "auto_trade_enabled": config.auto_trade_enabled,
                "fixed_lot_size": config.fixed_lot_size,
                "trailing_stop_enabled": config.trailing_stop_enabled,
                "take_profit_enabled": config.take_profit_enabled,
                "take_profit_points": config.take_profit_points,
                "desk_id": f"{acc_info['name']} ({acc_info['login']})" if acc_info.get("connected") else config.desk_id,
                "version": config.version,
                "killswitch": risk_gate.killswitch_active,
                "mt5_connected": acc_info.get("connected", False),
                "mt5_server": acc_info.get("server", "Demo"),
                "mt5_ping_ms": acc_info.get("ping_ms", 4.2),
                "account_equity": acc_info.get("equity", router.portfolio.net_equity),
                "account_balance": acc_info.get("balance", router.portfolio.net_equity),
                "network_status": router.portfolio.network_status.value if hasattr(router.portfolio.network_status, "value") else str(router.portfolio.network_status),
                "downtime_seconds": mt5_conn.downtime_duration_seconds,
                "last_reconciliation": router.portfolio.last_reconciliation.model_dump(mode="json") if router.portfolio.last_reconciliation else None
            },
            "portfolio": router.portfolio.model_dump(mode="json"),
            "ticks": {k: v.model_dump(mode="json") for k, v in current_ticks.items()},
            "pending_orders": [o.model_dump(mode="json") for o in router.pending_orders.values() if o.status == OrderStatus.PENDING],
            "last_reconciliation": router.portfolio.last_reconciliation.model_dump(mode="json") if router.portfolio.last_reconciliation else None,
            "agents": {k: v.get_telemetry() for k, v in swarm.items()},
            "consensus": current_consensus.model_dump(mode="json") if current_consensus else None,
            "risk_gate": current_risk_eval.model_dump(mode="json") if current_risk_eval else None,
            "recent_audit": [r.model_dump(mode="json") for r in ledger.get_recent(25)],
            "recent_orders": [o.model_dump(mode="json") for o in router.get_recent_orders(10)]
        }
        await websocket.send_json(jsonable_encoder(initial_state))
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "HEARTBEAT", "timestamp": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket client disconnected or error: {e}")
        manager.disconnect(websocket)

latest_backtest_report: Optional[BacktestReport] = None

class RunBacktestReq(BaseModel):
    symbol: str = "XAUUSD"
    candle_count: int = 150
    initial_equity: float = 1000000.0
    risk_per_trade_pct: float = 1.5

@app.post("/api/backtest/run")
async def run_backtest_endpoint(req: RunBacktestReq):
    global latest_backtest_report
    from datetime import timedelta
    candles: List[Candle] = []
    sym = req.symbol.upper()
    
    # Base price calculation from current ticks or sensible default
    if sym in current_ticks and current_ticks[sym].price > 0:
        base_price = current_ticks[sym].price
    elif "BTC" in sym:
        base_price = 67412.0
    elif "EUR" in sym:
        base_price = 1.0894
    elif "OIL" in sym:
        base_price = 81.24
    else:
        base_price = 2384.42

    # Synthesize realistic institutional candles with market wave cycles & volatility
    base_ts = datetime.now(timezone.utc) - timedelta(minutes=15 * req.candle_count)
    curr = base_price
    for i in range(req.candle_count):
        # Multi-cycle institutional order flow (trend waves + intraday oscillation)
        wave = math.sin(i / 5.0) * (curr * 0.005) + math.cos(i / 12.0) * (curr * 0.003)
        drift = (wave * 0.25) + ((random.random() - 0.49) * (curr * 0.002))
        curr += drift
        high = curr + abs(random.uniform(0.3, 1.2)) * (curr * 0.002)
        low = curr - abs(random.uniform(0.3, 1.2)) * (curr * 0.002)
        c = Candle(
            timestamp=base_ts + timedelta(minutes=15 * i),
            open=round(curr - drift, 4),
            high=round(max(high, curr, curr - drift), 4),
            low=round(min(low, curr, curr - drift), 4),
            close=round(curr, 4),
            volume=round(random.uniform(500.0, 3500.0), 1)
        )
        candles.append(c)

    cfg = BacktestConfig(
        initial_equity=req.initial_equity,
        risk_per_trade_pct=req.risk_per_trade_pct
    )
    engine = BacktestEngine(config=cfg)
    report = await engine.run_simulation(candles, symbol=sym)
    latest_backtest_report = report

    ev = ledger.record_event(
        source="SIMULATION",
        event_type="BACKTEST_COMPLETED",
        message=f"Historical Backtest completed for {sym}: {report.total_trades} trades, Win Rate: {report.win_rate_pct:.1f}%, Profit Factor: {report.profit_factor:.2f}, Final Equity: ${report.final_equity:,.2f}",
        payload={"symbol": sym, "final_equity": report.final_equity, "win_rate_pct": report.win_rate_pct, "profit_factor": report.profit_factor}
    )
    audit_db.persist_record(ev)

    await manager.broadcast({
        "type": "BACKTEST_REPORT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "report": report.model_dump(mode="json")
    })

    return report.model_dump(mode="json")

@app.get("/api/backtest/latest")
async def get_latest_backtest():
    if latest_backtest_report is None:
        raise HTTPException(status_code=404, detail="No backtest has been executed yet.")
    return latest_backtest_report.model_dump(mode="json")

# Mount static directory and root index
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({"status": "CYBER_SWARM_ONLINE", "version": config.version})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("cyber_swarm.server.app:app", host=config.host, port=config.port, reload=False)
