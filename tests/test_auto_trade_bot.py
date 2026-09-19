"""CYBER SWARM TRADING OS - Auto Trade Bot, Fixed 0.10 Lot & Trailing Stop Tests"""
import pytest
from datetime import datetime, UTC

from cyber_swarm.core.config import config
from cyber_swarm.core.models import (
    ConsensusResult,
    ConsensusState,
    OrderDirection,
    OrderType,
    OrderStatus,
    PortfolioState,
    MarketTick,
    Position
)
from cyber_swarm.risk.risk_gate import InstitutionalRiskGate
from cyber_swarm.execution.router import ExecutionRouter
from fastapi.testclient import TestClient
from cyber_swarm.server.app import app


@pytest.fixture
def risk_gate():
    config.auto_trade_enabled = True
    config.fixed_lot_size = 0.10
    config.trailing_stop_enabled = True
    return InstitutionalRiskGate()


@pytest.fixture
def router():
    r = ExecutionRouter()
    r.active_positions.clear()
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
        pending_orders=[]
    )
    return r


@pytest.fixture
def sample_tick():
    return MarketTick(
        symbol="XAUUSD",
        price=2730.0,
        bid=2729.8,
        ask=2730.2,
        spread=0.4,
        volume_24h=50000.0,
        change_pct=0.5,
        timestamp=datetime.now(UTC)
    )


@pytest.fixture
def sample_consensus():
    return ConsensusResult(
        cycle_id=101,
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        score=0.88,
        state=ConsensusState.HIGH_CONFIDENCE,
        participating_agents=["TIDAL", "NORO", "ZEPHR"],
        votes={},
        evidence_chain=["liquidity_sweep", "fvg_retest"]
    )


def test_fixed_lot_size_invariant_in_risk_gate(risk_gate, router, sample_tick, sample_consensus):
    """Invariant 9: lot_size must be strictly equal to config.fixed_lot_size (0.10)."""
    # 0.20 lot -> must be rejected
    eval_invalid = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, router.portfolio, lot_size=0.20)
    assert eval_invalid.approved is False
    assert any("FIXED_LOT_SIZE_VIOLATION" in r for r in eval_invalid.reasons)

    # 0.05 lot -> must be rejected
    eval_invalid_low = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, router.portfolio, lot_size=0.05)
    assert eval_invalid_low.approved is False
    assert any("FIXED_LOT_SIZE_VIOLATION" in r for r in eval_invalid_low.reasons)

    # 0.10 lot -> must pass
    eval_valid = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, router.portfolio, lot_size=0.10)
    assert eval_valid.approved is True
    assert eval_valid.lot_size == 0.10


def test_auto_trade_master_toggle_in_risk_gate(risk_gate, router, sample_tick, sample_consensus):
    """Invariant 8: AUTO_TRADE_DISABLED when auto_trade_enabled is False."""
    config.auto_trade_enabled = False
    eval_res = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, router.portfolio, lot_size=0.10)
    assert eval_res.approved is False
    assert any("AUTO_TRADE_DISABLED" in r for r in eval_res.reasons)

    # Re-enable
    config.auto_trade_enabled = True
    eval_res_on = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, router.portfolio, lot_size=0.10)
    assert eval_res_on.approved is True


@pytest.mark.asyncio
async def test_execution_router_enforces_fixed_lot_size(router, sample_tick, sample_consensus, risk_gate):
    """ExecutionRouter must always execute with config.fixed_lot_size (0.10)."""
    eval_res = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, router.portfolio, lot_size=0.10)
    order = await router.execute_order(eval_res, sample_consensus, sample_tick)
    assert order.lot_size == 0.10
    assert len(router.portfolio.open_positions) == 1
    assert router.portfolio.open_positions[0].lot_size == 0.10


def test_create_and_fill_buy_limit_order(router):
    """Auto Buy Limit order created below market and filled when price reaches limit."""
    order = router.create_pending_limit_order(
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=2725.0,
        cycle_id="cycle_test_01"
    )
    assert order.status == OrderStatus.PENDING
    assert order.lot_size == 0.10
    assert order.limit_price == 2725.0
    assert order.order_id in router.pending_orders

    # Tick at 2728.0 (above limit) -> should NOT fill
    tick_above = MarketTick(
        symbol="XAUUSD", price=2728.0, bid=2727.8, ask=2728.2,
        spread=0.4, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    filled = router.check_pending_orders(tick_above)
    assert len(filled) == 0
    assert order.status == OrderStatus.PENDING

    # Tick at 2724.5 (touches/crosses limit) -> must fill BUY_LIMIT
    tick_fill = MarketTick(
        symbol="XAUUSD", price=2724.5, bid=2724.3, ask=2724.7,
        spread=0.4, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    filled = router.check_pending_orders(tick_fill)
    assert len(filled) == 1
    assert filled[0].order_id == order.order_id
    assert filled[0].status == OrderStatus.FILLED
    assert filled[0].fill_price == tick_fill.ask
    # Position created
    assert len(router.portfolio.open_positions) == 1
    pos = router.portfolio.open_positions[0]
    assert pos.symbol == "XAUUSD"
    assert pos.direction == OrderDirection.BUY
    assert pos.entry_price == tick_fill.ask
    assert pos.lot_size == 0.10


def test_create_and_fill_sell_limit_order(router):
    """Auto Sell Limit order created above market and filled when price reaches limit."""
    order = router.create_pending_limit_order(
        symbol="BTCUSD",
        direction=OrderDirection.SELL,
        order_type=OrderType.SELL_LIMIT,
        limit_price=68500.0,
        cycle_id="cycle_test_02"
    )
    assert order.status == OrderStatus.PENDING
    assert order.lot_size == 0.10

    # Tick at 68200.0 (below limit) -> should NOT fill
    tick_below = MarketTick(
        symbol="BTCUSD", price=68200.0, bid=68190.0, ask=68210.0,
        spread=20.0, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    filled = router.check_pending_orders(tick_below)
    assert len(filled) == 0

    # Tick at 68550.0 (reaches limit) -> must fill SELL_LIMIT
    tick_fill = MarketTick(
        symbol="BTCUSD", price=68550.0, bid=68540.0, ask=68560.0,
        spread=20.0, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    filled = router.check_pending_orders(tick_fill)
    assert len(filled) == 1
    assert filled[0].status == OrderStatus.FILLED
    assert len(router.portfolio.open_positions) == 1
    pos = router.portfolio.open_positions[0]
    assert pos.symbol == "BTCUSD"
    assert pos.direction == OrderDirection.SELL
    assert pos.lot_size == 0.10


def test_cancel_pending_order(router):
    """Operator can cancel a pending limit order."""
    order = router.create_pending_limit_order(
        symbol="EURUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=1.0800,
        cycle_id="cycle_test_03"
    )
    assert order.status == OrderStatus.PENDING
    cancelled = router.cancel_pending_order(order.order_id)
    assert cancelled is not None
    assert cancelled.status == OrderStatus.CANCELLED
    # Check pending order no longer fills
    tick = MarketTick(
        symbol="EURUSD", price=1.0750, bid=1.0749, ask=1.0751,
        spread=0.0002, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    filled = router.check_pending_orders(tick)
    assert len(filled) == 0


def test_auto_trailing_stop_ratchet_and_closure(router):
    """Auto Trailing Stop ratchets SL in profit direction and auto-closes on breach."""
    # Seed an open BUY position on XAUUSD at 2730.0
    # XAUUSD profile: trail_distance = 8.0, trail_activation_delta = 4.0
    pos = Position(
        position_id="pos_trail_01",
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        lot_size=0.10,
        entry_price=2730.0,
        current_price=2730.0,
        unrealized_pnl=0.0,
        stop_loss=2722.0,
        take_profit=2760.0,
        highest_price=2730.0,
        lowest_price=2730.0,
        trail_distance=8.0,
        trail_activation_delta=4.0,
        trailing_active=False
    )
    router.active_positions[pos.position_id] = pos
    router.portfolio.open_positions = list(router.active_positions.values())

    # 1. Price moves to 2732.0 (profit +2.0 < activation delta +4.0) -> Trailing stays inactive
    tick_1 = MarketTick(
        symbol="XAUUSD", price=2732.0, bid=2731.8, ask=2732.2,
        spread=0.4, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    msgs = router.apply_trailing_stop(tick_1)
    assert len(msgs) == 0
    assert pos.trailing_active is False
    assert pos.stop_loss == 2722.0

    # 2. Price moves to 2736.0 (profit +6.0 >= +4.0 activation delta) -> Trailing activates!
    # Ratchet SL = 2736.0 - 8.0 = 2728.0 (higher than initial 2722.0)
    tick_2 = MarketTick(
        symbol="XAUUSD", price=2736.0, bid=2735.8, ask=2736.2,
        spread=0.4, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    msgs = router.apply_trailing_stop(tick_2)
    assert any("Trailing SL ratcheted" in m for m in msgs)
    assert pos.trailing_active is True
    assert pos.stop_loss == 2728.0

    # 3. Price rallies higher to 2742.0 -> SL ratchets to 2742.0 - 8.0 = 2734.0 (locked profit +$4.00!)
    tick_3 = MarketTick(
        symbol="XAUUSD", price=2742.0, bid=2741.8, ask=2742.2,
        spread=0.4, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    msgs = router.apply_trailing_stop(tick_3)
    assert pos.stop_loss == 2734.0
    assert pos.highest_price == 2742.0

    # 4. Price pulls back to 2733.5 (breaches ratcheted SL of 2734.0) -> Position auto-closes with locked profit!
    tick_4 = MarketTick(
        symbol="XAUUSD", price=2733.5, bid=2733.3, ask=2733.7,
        spread=0.4, volume_24h=100.0, change_pct=0.0, timestamp=datetime.now(UTC)
    )
    msgs = router.apply_trailing_stop(tick_4)
    assert any("Trailing Stop Triggered" in m for m in msgs)
    assert len(router.portfolio.open_positions) == 0
    assert router.portfolio.realized_pnl_mtd > 0  # Locked profit realized!


def test_fastapi_autotrade_endpoints():
    """Verify REST endpoints for autotrade bot, limit orders, and trailing stop."""
    client = TestClient(app)

    # 1. GET /api/autotrade
    res = client.get("/api/autotrade")
    assert res.status_code == 200
    data = res.json()
    assert "auto_trade_enabled" in data
    assert data["fixed_lot_size"] == 0.10

    # 2. POST /api/autotrade
    res_toggle = client.post("/api/autotrade", json={"enabled": False})
    assert res_toggle.status_code == 200
    assert res_toggle.json()["auto_trade_enabled"] is False

    res_toggle_on = client.post("/api/autotrade", json={"enabled": True})
    assert res_toggle_on.status_code == 200
    assert res_toggle_on.json()["auto_trade_enabled"] is True

    # 3. POST /api/orders/limit
    res_lmt = client.post("/api/orders/limit", json={
        "symbol": "XAUUSD",
        "direction": "BUY",
        "order_type": "BUY_LIMIT",
        "limit_price": 2720.50
    })
    assert res_lmt.status_code == 200
    order_data = res_lmt.json()["order"]
    assert order_data["symbol"] == "XAUUSD"
    assert order_data["lot_size"] == 0.10
    assert order_data["limit_price"] == 2720.50
    order_id = order_data["order_id"]

    # 4. DELETE /api/orders/pending/{order_id}
    res_del = client.delete(f"/api/orders/pending/{order_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "CANCELLED"
