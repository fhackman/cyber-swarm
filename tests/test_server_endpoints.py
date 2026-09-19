"""Integration Tests for CYBER SWARM TRADING OS - Server Endpoints & Telemetry"""
from fastapi.testclient import TestClient

from cyber_swarm.server.app import app

client = TestClient(app)


def test_index_page_returns_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "CYBER SWARM" in resp.text


def test_api_telemetry():
    resp = client.get("/api/telemetry")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "agents" in data
    assert "consensus" in data
    assert "NORO" in data["agents"]


def test_api_risk_killswitch_flow():
    # Trigger killswitch
    resp = client.post("/api/risk/killswitch", json={"action": "TRIGGER", "reason": "Test Killswitch"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["killswitch_active"] is True
    assert data["status"] == "ENGAGED"

    # Reset killswitch
    resp = client.post("/api/risk/killswitch", json={"action": "RESET"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["killswitch_active"] is False
    assert data["status"] == "DISENGAGED"


def test_api_ledger_integrity():
    resp = client.get("/api/ledger/integrity")
    assert resp.status_code == 200
    data = resp.json()
    assert "in_memory_valid" in data
    assert "sqlite_valid" in data
    assert data["in_memory_valid"] is True
    assert data["sqlite_valid"] is True


def test_api_cancel_nonexistent_pending_order():
    resp = client.delete("/api/orders/pending/NON_EXISTENT_ORDER_XYZ")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Pending order not found"


def test_api_network_reconcile_endpoint():
    resp = client.post("/api/network/reconcile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert "report" in data
    assert "total_reviewed" in data["report"]


def test_api_network_disconnect_and_reconnect():
    # Disconnect
    resp = client.post("/api/network/disconnect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "DISCONNECTED"

    # Reconnect
    resp = client.post("/api/network/reconnect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ["RECONNECTED", "RECONNECTING"]


def test_api_backtest_run():
    resp = client.post("/api/backtest/run", json={
        "symbol": "XAUUSD",
        "candle_count": 30,
        "initial_equity": 500000.0,
        "risk_per_trade_pct": 1.0
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert "report" in data
    assert data["report"]["symbol"] == "XAUUSD"
    assert "net_pnl" in data["report"]
    assert "sharpe_ratio" in data["report"]
