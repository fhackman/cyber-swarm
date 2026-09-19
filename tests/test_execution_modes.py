"""Unit & Integration Tests for CYBER SWARM TRADING OS - Execution Modes (LIVE, PAPER, BACKTEST, SAFE)"""
from fastapi.testclient import TestClient

from cyber_swarm.server.app import app
from cyber_swarm.core.config import config, ExecutionMode
from cyber_swarm.core.models import OrderStatus

client = TestClient(app)

def test_initial_mode_is_valid():
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data["config"]
    assert data["config"]["mode"] in ["LIVE", "PAPER", "BACKTEST", "SAFE"]

def test_set_mode_paper():
    resp = client.post("/api/mode", json={"mode": "PAPER"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "PAPER"
    assert config.mode == ExecutionMode.PAPER

def test_set_mode_live():
    resp = client.post("/api/mode", json={"mode": "LIVE"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "LIVE"
    assert config.mode == ExecutionMode.LIVE

def test_set_mode_backtest():
    resp = client.post("/api/mode", json={"mode": "BACKTEST"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "BACKTEST"
    assert config.mode == ExecutionMode.BACKTEST

def test_set_mode_safe():
    resp = client.post("/api/mode", json={"mode": "SAFE"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "SAFE"
    assert config.mode == ExecutionMode.SAFE

def test_safe_mode_strictly_blocks_manual_limit_orders():
    # Set mode to SAFE
    client.post("/api/mode", json={"mode": "SAFE"})
    assert config.mode == ExecutionMode.SAFE

    # Attempt to place order in SAFE mode
    resp = client.post("/api/orders/limit", json={
        "symbol": "XAUUSD",
        "direction": "BUY",
        "order_type": "BUY_LIMIT",
        "limit_price": 2350.0,
        "lot_size": 0.10
    })
    # Must fail-closed with 403 Forbidden
    assert resp.status_code == 403
    assert "SAFE MODE" in resp.json()["detail"]

def test_backtest_mode_blocks_live_limit_orders():
    # Set mode to BACKTEST
    client.post("/api/mode", json={"mode": "BACKTEST"})
    assert config.mode == ExecutionMode.BACKTEST

    # Attempt to place live limit order while in BACKTEST mode
    resp = client.post("/api/orders/limit", json={
        "symbol": "XAUUSD",
        "direction": "BUY",
        "order_type": "BUY_LIMIT",
        "limit_price": 2350.0,
        "lot_size": 0.10
    })
    assert resp.status_code == 400
    assert "BACKTEST MODE" in resp.json()["detail"]

def test_paper_mode_allows_limit_orders():
    # Set mode to PAPER
    client.post("/api/mode", json={"mode": "PAPER"})
    assert config.mode == ExecutionMode.PAPER

    resp = client.post("/api/orders/limit", json={
        "symbol": "XAUUSD",
        "direction": "BUY",
        "order_type": "BUY_LIMIT",
        "limit_price": 2350.0,
        "lot_size": 0.10
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["order"]["status"] == OrderStatus.PENDING

def test_run_backtest_simulation_api():
    # Call backtest execution endpoint
    resp = client.post("/api/backtest/run", json={
        "symbol": "XAUUSD",
        "candle_count": 50,
        "initial_equity": 500000.0,
        "risk_per_trade_pct": 1.5
    })
    assert resp.status_code == 200
    report = resp.json()
    assert report["symbol"] == "XAUUSD"
    assert "final_equity" in report
    assert "win_rate_pct" in report
    assert "max_drawdown_pct" in report
    assert "profit_factor" in report
    assert isinstance(report["trades"], list)

    # Check latest report endpoint
    resp_latest = client.get("/api/backtest/latest")
    assert resp_latest.status_code == 200
    latest = resp_latest.json()
    assert latest["symbol"] == "XAUUSD"

# Reset back to PAPER mode after tests
def test_cleanup_reset_to_paper():
    resp = client.post("/api/mode", json={"mode": "PAPER"})
    assert resp.status_code == 200
