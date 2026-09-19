"""CYBER SWARM TRADING OS - Auto Take Profit Engine (100 - 300 Points) Tests"""
import pytest
from datetime import datetime, UTC
from fastapi.testclient import TestClient

from cyber_swarm.core.config import config
from cyber_swarm.core.models import (
    ConsensusResult,
    ConsensusState,
    OrderDirection,
    OrderType,
    OrderStatus,
    PortfolioState,
    MarketTick,
    Position,
    RiskEvaluation
)
from cyber_swarm.execution.router import ExecutionRouter
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
        take_profit_enabled=True,
        take_profit_points=200
    )
    return r


@pytest.fixture
def client():
    return TestClient(app)


def test_take_profit_config_defaults():
    """Verify default take profit configuration and limits."""
    assert config.take_profit_enabled is True
    assert config.take_profit_points == 200
    assert config.take_profit_points_min == 100
    assert config.take_profit_points_max == 300
    assert config.point_sizes["XAUUSD"] == 0.01
    assert config.point_sizes["BTCUSD"] == 1.0
    assert config.point_sizes["EURUSD"] == 0.00001
    assert config.point_sizes["USOIL"] == 0.01


def test_calculate_take_profit_multi_asset(router):
    """Test point-to-price translation across multiple assets."""
    # XAUUSD BUY 200 pt -> +$2.00
    tp_gold_buy = router.calculate_take_profit("XAUUSD", OrderDirection.BUY, 2730.0, 200)
    assert tp_gold_buy == 2732.0

    # XAUUSD SELL 150 pt -> -$1.50
    tp_gold_sell = router.calculate_take_profit("XAUUSD", OrderDirection.SELL, 2730.0, 150)
    assert tp_gold_sell == 2728.5

    # BTCUSD BUY 300 pt -> +$300.00
    tp_btc_buy = router.calculate_take_profit("BTCUSD", OrderDirection.BUY, 65000.0, 300)
    assert tp_btc_buy == 65300.0

    # BTCUSD SELL 100 pt -> -$100.00
    tp_btc_sell = router.calculate_take_profit("BTCUSD", OrderDirection.SELL, 65000.0, 100)
    assert tp_btc_sell == 64900.0

    # EURUSD BUY 200 pt -> +0.00200
    tp_eur_buy = router.calculate_take_profit("EURUSD", OrderDirection.BUY, 1.08500, 200)
    assert round(tp_eur_buy, 5) == 1.08700

    # EURUSD SELL 100 pt -> -0.00100
    tp_eur_sell = router.calculate_take_profit("EURUSD", OrderDirection.SELL, 1.08500, 100)
    assert round(tp_eur_sell, 5) == 1.08400

    # USOIL BUY 250 pt -> +$2.50
    tp_oil_buy = router.calculate_take_profit("USOIL", OrderDirection.BUY, 80.00, 250)
    assert tp_oil_buy == 82.50


def test_calculate_take_profit_point_clamping(router):
    """Test that points outside 100-300 are clamped safely."""
    # Underflow (50 pt -> clamped to 100 pt = $1.00)
    tp_under = router.calculate_take_profit("XAUUSD", OrderDirection.BUY, 2700.0, 50)
    assert tp_under == 2701.0

    # Overflow (500 pt -> clamped to 300 pt = $3.00)
    tp_over = router.calculate_take_profit("XAUUSD", OrderDirection.BUY, 2700.0, 500)
    assert tp_over == 2703.0


@pytest.mark.asyncio
async def test_execute_order_assigns_take_profit(router):
    """Test that direct market execution assigns take profit when enabled."""
    tick = MarketTick(
        symbol="XAUUSD",
        price=2730.0,
        bid=2729.8,
        ask=2730.2,
        spread=0.4,
        volume_24h=50000.0,
        change_pct=0.5,
        timestamp=datetime.now(UTC)
    )
    consensus = ConsensusResult(
        cycle_id=1,
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        score=0.90,
        state=ConsensusState.HIGH_CONFIDENCE,
        participating_agents=["TIDAL"],
        votes={},
        evidence_chain=[]
    )
    risk_approval = RiskEvaluation(
        approved=True,
        direction=OrderDirection.BUY,
        symbol="XAUUSD",
        lot_size=0.10,
        estimated_risk_pct=1.0,
        current_drawdown_pct=0.0,
        exposure_pct=5.0,
        reasons=["All rules passed"]
    )

    order = await router.execute_order(risk_approval, consensus, tick)
    assert order.take_profit is not None
    assert order.take_profit_points == 200
    # Ask fill is 2730.2 -> TP is 2730.2 + 2.0 = 2732.2
    assert round(order.take_profit, 2) == 2732.2

    # Check position created in active_positions
    pos = list(router.active_positions.values())[0]
    assert pos.take_profit is not None
    assert pos.take_profit_points == 200
    assert round(pos.take_profit, 2) == 2732.2


def test_pending_limit_order_take_profit(router):
    """Test that limit orders calculate and carry forward take profit."""
    order = router.create_pending_limit_order(
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        order_type=OrderType.BUY_LIMIT,
        limit_price=2720.0,
        cycle_id="test_1",
        take_profit_points=250
    )
    assert order.take_profit_points == 250
    # 250 pt = $2.50 -> TP = 2722.50
    assert order.take_profit == 2722.50

    # Simulate fill with tick at ask 2719.5 (below 2720.0)
    fill_tick = MarketTick(
        symbol="XAUUSD",
        price=2719.5,
        bid=2719.3,
        ask=2719.5,
        spread=0.2,
        volume_24h=50000.0,
        change_pct=0.1,
        timestamp=datetime.now(UTC)
    )
    filled_orders = router.check_pending_orders(fill_tick)
    assert len(filled_orders) == 1
    assert filled_orders[0].status == OrderStatus.FILLED

    pos = list(router.active_positions.values())[0]
    assert pos.take_profit == 2722.50
    assert pos.take_profit_points == 250


def test_apply_take_profit_buy_trigger(router):
    """Test auto-closing a BUY position when bid price hits or exceeds take profit."""
    pos = Position(
        position_id="pos_buy_tp",
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        lot_size=0.10,
        entry_price=2730.0,
        current_price=2730.0,
        take_profit=2732.0,
        take_profit_points=200,
        open_time=datetime.now(UTC),
        trailing_active=False
    )
    router.active_positions[pos.position_id] = pos
    router.portfolio.open_positions = [pos]

    # Tick 1: Bid at 2731.0 (below TP 2732.0) -> No close
    tick1 = MarketTick(
        symbol="XAUUSD",
        price=2731.0,
        bid=2731.0,
        ask=2731.2,
        spread=0.2,
        volume_24h=50000.0,
        change_pct=0.2,
        timestamp=datetime.now(UTC)
    )
    msgs1 = router.apply_take_profit(tick1)
    assert len(msgs1) == 0
    assert "pos_buy_tp" in router.active_positions

    # Tick 2: Bid reaches 2732.5 (>= TP 2732.0) -> Position auto closes!
    tick2 = MarketTick(
        symbol="XAUUSD",
        price=2732.5,
        bid=2732.5,
        ask=2732.7,
        spread=0.2,
        volume_24h=50000.0,
        change_pct=0.5,
        timestamp=datetime.now(UTC)
    )
    msgs2 = router.apply_take_profit(tick2)
    assert len(msgs2) == 1
    assert "Auto Take Profit Hit" in msgs2[0]
    assert "pos_buy_tp" not in router.active_positions
    assert len(router.portfolio.open_positions) == 0
    assert router.portfolio.realized_pnl_mtd > 0


def test_apply_take_profit_sell_trigger(router):
    """Test auto-closing a SELL position when ask price drops to or below take profit."""
    pos = Position(
        position_id="pos_sell_tp",
        symbol="XAUUSD",
        direction=OrderDirection.SELL,
        lot_size=0.10,
        entry_price=2730.0,
        current_price=2730.0,
        take_profit=2728.0,
        take_profit_points=200,
        open_time=datetime.now(UTC),
        trailing_active=False
    )
    router.active_positions[pos.position_id] = pos
    router.portfolio.open_positions = [pos]

    # Tick 1: Ask at 2729.0 (above TP 2728.0) -> No close
    tick1 = MarketTick(
        symbol="XAUUSD",
        price=2729.0,
        bid=2728.8,
        ask=2729.0,
        spread=0.2,
        volume_24h=50000.0,
        change_pct=-0.2,
        timestamp=datetime.now(UTC)
    )
    msgs1 = router.apply_take_profit(tick1)
    assert len(msgs1) == 0
    assert "pos_sell_tp" in router.active_positions

    # Tick 2: Ask at 2727.8 (<= TP 2728.0) -> Position auto closes!
    tick2 = MarketTick(
        symbol="XAUUSD",
        price=2727.8,
        bid=2727.6,
        ask=2727.8,
        spread=0.2,
        volume_24h=50000.0,
        change_pct=-0.5,
        timestamp=datetime.now(UTC)
    )
    msgs2 = router.apply_take_profit(tick2)
    assert len(msgs2) == 1
    assert "Auto Take Profit Hit" in msgs2[0]
    assert "pos_sell_tp" not in router.active_positions
    assert len(router.portfolio.open_positions) == 0
    assert router.portfolio.realized_pnl_mtd > 0


def test_apply_take_profit_disabled_toggle(router):
    """When take_profit_enabled is False, position is not closed even if price reaches TP."""
    config.take_profit_enabled = False
    pos = Position(
        position_id="pos_tp_disabled",
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        lot_size=0.10,
        entry_price=2730.0,
        current_price=2730.0,
        take_profit=2732.0,
        take_profit_points=200,
        open_time=datetime.now(UTC)
    )
    router.active_positions[pos.position_id] = pos

    tick = MarketTick(
        symbol="XAUUSD",
        price=2735.0,
        bid=2735.0,
        ask=2735.2,
        spread=0.2,
        volume_24h=50000.0,
        change_pct=0.5,
        timestamp=datetime.now(UTC)
    )
    msgs = router.apply_take_profit(tick)
    assert len(msgs) == 0
    assert "pos_tp_disabled" in router.active_positions


def test_rest_api_takeprofit(client):
    """Test GET and POST /api/takeprofit endpoints."""
    # GET initial config
    res = client.get("/api/takeprofit")
    assert res.status_code == 200
    data = res.json()
    assert data["take_profit_enabled"] is True
    assert data["take_profit_points"] == 200
    assert data["take_profit_points_min"] == 100
    assert data["take_profit_points_max"] == 300

    # POST valid update: 250 points
    res_post = client.post("/api/takeprofit", json={"points": 250, "enabled": True})
    assert res_post.status_code == 200
    data_post = res_post.json()
    assert data_post["take_profit_points"] == 250
    assert config.take_profit_points == 250

    # POST invalid update: < 100 points
    res_under = client.post("/api/takeprofit", json={"points": 80})
    assert res_under.status_code == 400
    assert "between 100 and 300" in res_under.json()["detail"]

    # POST invalid update: > 300 points
    res_over = client.post("/api/takeprofit", json={"points": 350})
    assert res_over.status_code == 400
    assert "between 100 and 300" in res_over.json()["detail"]

    # POST toggle disable
    res_toggle = client.post("/api/takeprofit", json={"enabled": False})
    assert res_toggle.status_code == 200
    assert res_toggle.json()["take_profit_enabled"] is False
    assert config.take_profit_enabled is False


def test_rest_api_limit_order_with_takeprofit(client):
    """Test placing a limit order with optional take profit points."""
    # Valid limit order with 150 TP points
    res = client.post("/api/orders/limit", json={
        "symbol": "XAUUSD",
        "direction": "BUY",
        "order_type": "BUY_LIMIT",
        "limit_price": 2725.0,
        "take_profit_points": 150
    })
    assert res.status_code == 200
    order_data = res.json()["order"]
    assert order_data["take_profit_points"] == 150
    assert order_data["take_profit"] == 2726.50

    # Invalid limit order with out-of-bounds TP points (50 pt)
    res_invalid = client.post("/api/orders/limit", json={
        "symbol": "XAUUSD",
        "direction": "BUY",
        "order_type": "BUY_LIMIT",
        "limit_price": 2725.0,
        "take_profit_points": 50
    })
    assert res_invalid.status_code == 400
    assert "between 100 and 300" in res_invalid.json()["detail"]
