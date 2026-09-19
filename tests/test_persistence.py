"""Unit Tests for SQLite Cryptographic Audit Persistence"""
import hashlib
import json

from cyber_swarm.audit.ledger import AuditRecord
from cyber_swarm.audit.persistence import AuditPersistence
from cyber_swarm.core.models import OrderDirection, OrderStatus, TradeOrder


def test_audit_persistence_crud(tmp_path):
    db_file = tmp_path / "test_audit.db"
    store = AuditPersistence(db_file)

    p1 = {"key": "val1"}
    h0 = "0" * 64
    b1 = f"112:00:00.000SYSTEMTEST_INITTest record 1{json.dumps(p1, sort_keys=True)}{h0}"
    h1 = hashlib.sha256(b1.encode()).hexdigest()

    rec1 = AuditRecord(
        index=1,
        timestamp="12:00:00.000",
        source="SYSTEM",
        event_type="TEST_INIT",
        message="Test record 1",
        payload=p1,
        prev_hash=h0,
        hash=h1
    )

    p2 = {"approved": True}
    b2 = f"212:00:01.000RUNERISK_CHECKRisk passed{json.dumps(p2, sort_keys=True)}{h1}"
    h2 = hashlib.sha256(b2.encode()).hexdigest()

    rec2 = AuditRecord(
        index=2,
        timestamp="12:00:01.000",
        source="RUNE",
        event_type="RISK_CHECK",
        message="Risk passed",
        payload=p2,
        prev_hash=h1,
        hash=h2
    )

    store.persist_record(rec1)
    store.persist_record(rec2)

    loaded = store.load_all_records()
    assert len(loaded) == 2
    assert loaded[0].index == 1
    assert loaded[1].source == "RUNE"
    assert store.verify_stored_integrity() is True

def test_trade_order_persistence(tmp_path):
    db_file = tmp_path / "test_orders.db"
    store = AuditPersistence(db_file)

    order = TradeOrder(
        order_id="ORD-TEST-001",
        cycle_id=100,
        symbol="XAUUSD",
        direction=OrderDirection.BUY,
        lot_size=1.0,
        target_price=2380.0,
        fill_price=2380.25,
        status=OrderStatus.FILLED,
        decision_trace=["Consensus 85%", "Risk Approved"]
    )
    store.persist_order(order)

    # Reopen database and verify order row exists
    import sqlite3
    with sqlite3.connect(str(store.db_path)) as conn:
        row = conn.cursor().execute("SELECT order_id, symbol FROM trade_orders WHERE order_id = ?", ("ORD-TEST-001",)).fetchone()
        assert row is not None
        assert row[0] == "ORD-TEST-001"
        assert row[1] == "XAUUSD"
