"""CYBER SWARM TRADING OS - Network Reconnection & Pending Order Reconciliation Tests"""
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from cyber_swarm.core.config import config
from cyber_swarm.core.models import (
    TradeOrder,
    OrderStatus,
    OrderDirection,
    OrderType,
    Position,
    PortfolioState,
    MarketTick,
    ConsensusResult,
    ConsensusState,
    NetworkStatus,
    ReconciliationAction,
    ReconciliationReport
)
from cyber_swarm.execution.router import ExecutionRouter
from cyber_swarm.execution.mt5_connector import MT5Connector
from cyber_swarm.server.app import app


@pytest.fixture(autouse=True)
def reset_config():
    """Reset configuration to defaults before each test."""
    config.auto_trade_enabled = True
    config.fixed_lot_size = 0.10
    config.trailing_stop_enabled = True
    config.take_profit_enabled = True
    config.take_profit_points = 200
    config.take_profit_points_min = 100
    config.take_profit_points_max = 300
    config.network_reconciliation_enabled = True
    config.max_pending_order_ttl_seconds = 3600
    config.reconnect_price_drift_max_pct = 0.005


@pytest.fixture
def router():
    r = ExecutionRouter()
    r.active_positions.clear()
    r.pending_orders.clear()
    r.orders.clear()
    r.portfolio = PortfolioState(
        net_equity=100000.0,
        realized_pnl_mtd=0.0,
        unrealized_pnl=0.0,
        daily_drawdown_pct=0.0,
        max_drawdown_pct=0.0,
        risk_exposure_pct=0.0,
        win_rate_pct=0.0,
        total_trades=0,
        volume_24h_usd=0.0,
        open_positions=[],
        pending_orders=[],
        network_status=NetworkStatus.ONLINE
    )
    return r


@pytest.fixture
def client():
    return TestClient(app)


def test_network_state_machine():
    """Verify network state transitions: ONLINE -> DISCONNECTED -> RECONCILING -> SYNCED."""
    mt5 = MT5Connector()
    mt5.connected = True
    mt5.network_status = NetworkStatus.ONLINE

    # Simulate network disconnect
    mt5.simulate_network_disconnect()
    assert mt5.connected is False
    assert mt5.network_status == NetworkStatus.DISCONNECTED
    assert mt5.disconnected_at is not None

    # Simulate network reconnection
    mt5.simulate_network_reconnect(downtime_seconds=12.5)
    assert mt5.connected is True
    assert mt5.network_status == NetworkStatus.RECONCILING
    assert mt5.reconnected_event is True
    assert mt5.downtime_duration_seconds == 12.5


def test_price_inversion_cancellation(router):
    """
    Condition 1: Orders crossed by market price during disconnect without broker fill
    must be cancelled (Fail-Closed principle).
    """
    # 1. Inverted BUY_LIMIT (limit is 2720.00, but current market ask is 2715.00)
    buy_order = router.create_pending_limit_order(
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=2720.00
    )
    assert buy_order.order_id in router.pending_orders

    # 2. Inverted SELL_LIMIT (limit is 65000.00, but current market bid is 65500.00)
    sell_order = router.create_pending_limit_order(
        symbol="BTCUSD",
        direction=OrderDirection.SELL,
        order_type=OrderType.SELL_LIMIT,
        limit_price=65000.00
    )
    assert sell_order.order_id in router.pending_orders

    ticks = {
        "XAUUSD": MarketTick(symbol="XAUUSD", price=2715.0, bid=2714.8, ask=2715.2, spread=0.4, volume_24h=1000, change_pct=0.5),
        "BTCUSD": MarketTick(symbol="BTCUSD", price=65500.0, bid=65490.0, ask=65510.0, spread=20.0, volume_24h=5000, change_pct=1.2)
    }

    report = router.reconcile_pending_orders(
        current_ticks=ticks,
        downtime_seconds=15.0
    )

    assert report.total_reviewed == 2
    assert report.cancelled_count == 2
    assert report.retained_count == 0
    assert len(router.pending_orders) == 0

    assert buy_order.status == OrderStatus.CANCELLED
    assert sell_order.status == OrderStatus.CANCELLED
    assert "PRICE_INVERTED_DURING_DOWNTIME" in report.records[0].reason
    assert "PRICE_INVERTED_DURING_DOWNTIME" in report.records[1].reason


def test_swarm_consensus_reversal_cancellation(router):
    """
    Condition 2: Cancel pending order if swarm deliberation reversed in opposite direction.
    """
    # BUY_LIMIT on EURUSD at 1.0800 (market is 1.0850, not inverted)
    order = router.create_pending_limit_order(
        symbol="EURUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=1.0800
    )

    ticks = {
        "EURUSD": MarketTick(symbol="EURUSD", price=1.0850, bid=1.0849, ask=1.0851, spread=0.0002, volume_24h=100, change_pct=0.1)
    }

    # Swarm reversed to high conviction SELL (88%)
    consensus = {
        "EURUSD": ConsensusResult(
            cycle_id=101,
            symbol="EURUSD",
            direction=OrderDirection.SELL,
            score=0.88,
            state=ConsensusState.HIGH_CONFIDENCE,
            participating_agents=["NORO", "TIDAL"],
            votes={},
            evidence_chain=["Orderbook flipped"]
        )
    }

    report = router.reconcile_pending_orders(
        current_ticks=ticks,
        current_consensus=consensus,
        downtime_seconds=8.0
    )

    assert report.cancelled_count == 1
    assert order.status == OrderStatus.CANCELLED
    assert report.records[0].action == ReconciliationAction.CANCEL
    assert "SWARM_CONSENSUS_REVERSED" in report.records[0].reason
    assert len(router.pending_orders) == 0


def test_institutional_risk_invariant_breach(router):
    """
    Condition 3: Institutional Risk Invariants (Strict 0.10 lot size and TP 100-300 pt).
    """
    # Create an invalid order with wrong lot size (0.50)
    order = router.create_pending_limit_order(
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=2700.00
    )
    # Manually tamper lot_size to test invariant enforcement
    order.lot_size = 0.50

    ticks = {
        "XAUUSD": MarketTick(symbol="XAUUSD", price=2750.0, bid=2749.8, ask=2750.2, spread=0.4, volume_24h=100, change_pct=0.1)
    }

    report = router.reconcile_pending_orders(
        current_ticks=ticks,
        downtime_seconds=5.0
    )

    assert report.cancelled_count == 1
    assert order.status == OrderStatus.CANCELLED
    assert "RISK_INVARIANT_BREACH" in report.records[0].reason


def test_stale_order_ttl_expiration(router):
    """
    Condition 4: Stale limit orders pending longer than max TTL or through extended outage are purged.
    """
    order = router.create_pending_limit_order(
        symbol="USOIL",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=75.00
    )
    # Set order timestamp to 4000 seconds ago
    order.timestamp = datetime.now(timezone.utc) - timedelta(seconds=4000)

    ticks = {
        "USOIL": MarketTick(symbol="USOIL", price=80.0, bid=79.95, ask=80.05, spread=0.1, volume_24h=100, change_pct=0.1)
    }

    report = router.reconcile_pending_orders(
        current_ticks=ticks,
        downtime_seconds=10.0
    )

    assert report.cancelled_count == 1
    assert order.status == OrderStatus.CANCELLED
    assert "ORDER_TTL_EXPIRED" in report.records[0].reason


def test_broker_offline_fill_adoption(router):
    """
    Condition 5: Order filled by MT5 terminal while offline is adopted as active position with TP & Trailing Stop.
    """
    order = router.create_pending_limit_order(
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=2720.00,
        take_profit_points=250
    )

    ticks = {
        "XAUUSD": MarketTick(symbol="XAUUSD", price=2725.0, bid=2724.8, ask=2725.2, spread=0.4, volume_24h=100, change_pct=0.1)
    }

    # Simulate broker report stating order was FILLED
    mt5_filled = [
        TradeOrder(
            order_id=order.order_id,
            symbol="XAUUSD",
            direction=OrderDirection.BUY,
            order_type=OrderType.BUY_LIMIT,
            limit_price=2720.00,
            fill_price=2720.00,
            lot_size=0.10,
            status=OrderStatus.FILLED,
            target_price=2720.00
        )
    ]

    report = router.reconcile_pending_orders(
        current_ticks=ticks,
        mt5_orders=mt5_filled,
        downtime_seconds=20.0
    )

    assert report.total_reviewed == 1
    assert report.filled_count == 1
    assert report.cancelled_count == 0
    assert report.records[0].action == ReconciliationAction.ADOPT_FILLED
    assert len(router.pending_orders) == 0

    # Verify adopted into active_positions
    pos_id = f"POS-XAUUSD-{order.order_id[-4:]}"
    assert pos_id in router.active_positions
    pos = router.active_positions[pos_id]
    assert pos.symbol == "XAUUSD"
    assert pos.direction == OrderDirection.BUY
    assert pos.lot_size == 0.10
    assert pos.entry_price == 2720.00
    assert pos.take_profit_points == 250
    assert pos.trailing_active is True


def test_valid_order_retained(router):
    """
    Valid order meeting all 5 conditions is retained in the active pending orderbook.
    """
    order = router.create_pending_limit_order(
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=2700.00,
        take_profit_points=200
    )

    # Market is at 2720.00 (above buy limit -> normal pending limit order)
    ticks = {
        "XAUUSD": MarketTick(symbol="XAUUSD", price=2720.0, bid=2719.8, ask=2720.2, spread=0.4, volume_24h=100, change_pct=0.1)
    }

    # Swarm agrees with BUY direction (80%)
    consensus = {
        "XAUUSD": ConsensusResult(
            cycle_id=102,
            symbol="XAUUSD",
            direction=OrderDirection.BUY,
            score=0.80,
            state=ConsensusState.SIGNAL,
            participating_agents=["NORO"],
            votes={},
            evidence_chain=["Bullish SMC"]
        )
    }

    report = router.reconcile_pending_orders(
        current_ticks=ticks,
        current_consensus=consensus,
        downtime_seconds=5.0
    )

    assert report.total_reviewed == 1
    assert report.retained_count == 1
    assert report.cancelled_count == 0
    assert report.records[0].action == ReconciliationAction.RETAIN
    assert order.order_id in router.pending_orders
    assert router.portfolio.network_status == NetworkStatus.SYNCED


def test_rest_api_network_endpoints(client):
    """Verify GET /api/network/status and POST /api/network/reconcile."""
    # 1. GET status
    resp = client.get("/api/network/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data
    assert "network_status" in data
    assert "ping_ms" in data

    # 2. Place a pending order and trigger manual reconciliation
    client.post("/api/orders/limit", json={
        "symbol": "XAUUSD",
        "direction": "BUY",
        "order_type": "BUY_LIMIT",
        "limit_price": 2700.00,
        "take_profit_points": 200
    })

    # Trigger POST reconcile
    rec_resp = client.post("/api/network/reconcile")
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["status"] == "SUCCESS"
    assert "report" in rec_data
    assert rec_data["report"]["total_reviewed"] >= 1
