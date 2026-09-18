"""CYBER SWARM TRADING OS - Test Suite: Adjustable Lot Size (0.01 - 5.00)"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from cyber_swarm.core.config import config
from cyber_swarm.core.models import (
    ConsensusResult,
    ConsensusState,
    OrderDirection,
    OrderType,
    OrderStatus,
    PortfolioState,
    MarketTick
)
from cyber_swarm.risk.risk_gate import InstitutionalRiskGate
from cyber_swarm.execution.router import ExecutionRouter
from cyber_swarm.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def risk_gate():
    return InstitutionalRiskGate()


@pytest.fixture
def router():
    return ExecutionRouter()


@pytest.fixture
def base_portfolio():
    return PortfolioState(
        net_equity=100000.0,
        realized_pnl_mtd=5000.0,
        unrealized_pnl=1000.0,
        daily_drawdown_pct=1.5,
        max_drawdown_pct=2.0,
        risk_exposure_pct=15.0,
        win_rate_pct=70.0,
        total_trades=50,
        volume_24h_usd=1000000.0,
        open_positions=[]
    )


@pytest.fixture
def sample_tick():
    return MarketTick(
        symbol="XAUUSD",
        price=2384.42,
        bid=2384.30,
        ask=2384.55,
        spread=0.25,
        volume_24h=50000.0,
        change_pct=0.84,
        timestamp=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_consensus():
    return ConsensusResult(
        cycle_id=901,
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        score=0.88,
        state=ConsensusState.HIGH_CONFIDENCE,
        participating_agents=["NORO", "TIDAL"],
        votes={},
        evidence_chain=["Strong SMC test"]
    )


def test_config_lot_size_defaults_and_bounds():
    """Verify config defaults, bounds, step, and presets."""
    assert config.fixed_lot_size == 0.10
    assert config.min_lot_size == 0.01
    assert config.max_lot_size == 5.00
    assert config.lot_step == 0.01
    assert config.lot_presets == [0.01, 0.05, 0.10, 0.20, 0.50, 1.00]


def test_api_get_lot_size(client):
    """GET /api/config/lot-size should return current lot configuration."""
    config.fixed_lot_size = 0.10
    resp = client.get("/api/config/lot-size")
    assert resp.status_code == 200
    data = resp.json()
    assert data["lot_size"] == 0.10
    assert data["min_lot_size"] == 0.01
    assert data["max_lot_size"] == 5.00
    assert data["lot_step"] == 0.01
    assert data["lot_presets"] == [0.01, 0.05, 0.10, 0.20, 0.50, 1.00]


def test_api_set_lot_size_valid(client):
    """POST /api/config/lot-size with valid lot size updates system and ledger."""
    try:
        resp = client.post("/api/config/lot-size", json={"lot_size": 0.25})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["lot_size"] == 0.25
        assert config.fixed_lot_size == 0.25

        # Also verify presets work
        for preset in [0.01, 0.05, 0.50, 1.00]:
            r = client.post("/api/config/lot-size", json={"lot_size": preset})
            assert r.status_code == 200
            assert r.json()["lot_size"] == preset
            assert config.fixed_lot_size == preset
    finally:
        config.fixed_lot_size = 0.10


def test_api_set_lot_size_invalid_bounds(client):
    """POST /api/config/lot-size rejects lots below 0.01 or above 5.00 with HTTP 400."""
    # Under minimum
    resp_low = client.post("/api/config/lot-size", json={"lot_size": 0.005})
    assert resp_low.status_code == 400
    assert "between 0.01 and 5.0" in resp_low.json()["detail"]

    # Negative lot
    resp_neg = client.post("/api/config/lot-size", json={"lot_size": -0.10})
    assert resp_neg.status_code == 400

    # Over maximum
    resp_high = client.post("/api/config/lot-size", json={"lot_size": 5.50})
    assert resp_high.status_code == 400
    assert "between 0.01 and 5.0" in resp_high.json()["detail"]


def test_risk_gate_evaluation_with_adjusted_lot(risk_gate, sample_consensus, sample_tick, base_portfolio):
    """InstitutionalRiskGate should validate adjusted lot size and scale risk dynamically."""
    try:
        config.fixed_lot_size = 0.20
        eval_result = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio, lot_size=0.20)
        assert eval_result.approved is True
        assert eval_result.lot_size == 0.20
        # 1.45 * (0.20 / 0.10) = 2.90%
        assert eval_result.estimated_risk_pct == 2.90

        # Now test minimum lot 0.01
        config.fixed_lot_size = 0.01
        eval_min = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio, lot_size=0.01)
        assert eval_min.approved is True
        assert eval_min.lot_size == 0.01
        # 1.45 * (0.01 / 0.10) = 0.145 -> round to 0.14% in IEEE 754
        assert eval_min.estimated_risk_pct == round(1.45 * (0.01 / 0.10), 2)

        # Test rejection on out-of-bounds lot (< min_lot_size)
        config.fixed_lot_size = 0.10
        eval_bad = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio, lot_size=0.005)
        assert eval_bad.approved is False
        assert any("LOT_SIZE_OUT_OF_BOUNDS" in r for r in eval_bad.reasons)

        # Test rejection on in-bounds but mismatched lot
        eval_mismatch = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio, lot_size=0.05)
        assert eval_mismatch.approved is False
        assert any("FIXED_LOT_SIZE_VIOLATION" in r for r in eval_mismatch.reasons)
    finally:
        config.fixed_lot_size = 0.10


def test_router_create_pending_limit_order_adjustable_lot(router):
    """Router should support custom lot sizes on pending limit orders."""
    try:
        config.fixed_lot_size = 0.10

        # 1. Default lot size (inherits fixed_lot_size = 0.10)
        order1 = router.create_pending_limit_order(
            symbol="XAUUSD",
            direction=OrderDirection.BUY,
            order_type=OrderType.BUY_LIMIT,
            limit_price=2700.00
        )
        assert order1.lot_size == 0.10

        # 2. Explicit custom lot size = 0.05
        order2 = router.create_pending_limit_order(
            symbol="BTCUSD",
            direction=OrderDirection.SELL,
            order_type=OrderType.SELL_LIMIT,
            limit_price=68000.00,
            lot_size=0.05
        )
        assert order2.lot_size == 0.05

        # 3. Lot size clamping to bounds [0.01, 5.00]
        order3 = router.create_pending_limit_order(
            symbol="EURUSD",
            direction=OrderDirection.BUY,
            order_type=OrderType.BUY_LIMIT,
            limit_price=1.0800,
            lot_size=10.00  # Should clamp to 5.00
        )
        assert order3.lot_size == 5.00

        order4 = router.create_pending_limit_order(
            symbol="USOIL",
            direction=OrderDirection.BUY,
            order_type=OrderType.BUY_LIMIT,
            limit_price=75.00,
            lot_size=0.001  # Should clamp to 0.01
        )
        assert order4.lot_size == 0.01
    finally:
        config.fixed_lot_size = 0.10


def test_api_manual_limit_order_custom_lot(client):
    """POST /api/orders/limit allows specifying custom lot size within bounds."""
    try:
        config.fixed_lot_size = 0.10
        resp = client.post("/api/orders/limit", json={
            "symbol": "XAUUSD",
            "direction": "BUY",
            "order_type": "BUY_LIMIT",
            "limit_price": 2700.00,
            "take_profit_points": 200,
            "lot_size": 0.50
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["order"]["lot_size"] == 0.50

        # Invalid out-of-bounds lot on limit order
        resp_bad = client.post("/api/orders/limit", json={
            "symbol": "XAUUSD",
            "direction": "BUY",
            "order_type": "BUY_LIMIT",
            "limit_price": 2700.00,
            "lot_size": 9.99
        })
        assert resp_bad.status_code == 400
        assert "between 0.01 and 5.0" in resp_bad.json()["detail"]
    finally:
        config.fixed_lot_size = 0.10


def test_reconciliation_with_adjusted_lot_size(router):
    """Reconciliation should validate against currently configured lot size and bounds."""
    try:
        # Operator configured lot size to 0.20
        config.fixed_lot_size = 0.20

        # Valid order matching active configured lot size
        order_valid = router.create_pending_limit_order(
            symbol="XAUUSD",
            direction=OrderDirection.BUY,
            order_type=OrderType.BUY_LIMIT,
            limit_price=2700.00,
            lot_size=0.20
        )

        # Invalid order with mismatched/out-of-bounds lot size
        order_invalid = router.create_pending_limit_order(
            symbol="BTCUSD",
            direction=OrderDirection.SELL,
            order_type=OrderType.SELL_LIMIT,
            limit_price=69000.00,
            lot_size=0.05
        )

        ticks = {
            "XAUUSD": MarketTick(symbol="XAUUSD", price=2750.0, bid=2749.8, ask=2750.2, spread=0.4, volume_24h=100, change_pct=0.1),
            "BTCUSD": MarketTick(symbol="BTCUSD", price=65000.0, bid=64990.0, ask=65010.0, spread=20.0, volume_24h=100, change_pct=0.1)
        }

        report = router.reconcile_pending_orders(
            current_ticks=ticks,
            downtime_seconds=5.0
        )

        assert report.total_reviewed == 2
        assert report.retained_count == 1
        assert report.cancelled_count == 1

        assert order_valid.status == OrderStatus.PENDING
        assert order_invalid.status == OrderStatus.CANCELLED
        assert "RISK_INVARIANT_BREACH" in report.records[1].reason
    finally:
        config.fixed_lot_size = 0.10
