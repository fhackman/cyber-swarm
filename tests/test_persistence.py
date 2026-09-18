"""Unit Tests for SQLite Cryptographic Audit Persistence"""
import os
from pathlib import Path
from cyber_swarm.audit.persistence import AuditPersistence
from cyber_swarm.audit.ledger import AuditRecord
from cyber_swarm.core.models import TradeOrder, OrderDirection, OrderStatus

def test_audit_persistence_crud(tmp_path):
    db_file = tmp_path / "test_audit.db"
    store = AuditPersistence(db_file)

    rec1 = AuditRecord(
        index=1,
        timestamp="12:00:00.000",
        source="SYSTEM",
        event_type="TEST_INIT",
        message="Test record 1",
        payload={"key": "val1"},
        prev_hash="0" * 64,
        hash="a" * 64
    )
    rec2 = AuditRecord(
        index=2,
        timestamp="12:00:01.000",
        source="RUNE",
        event_type="RISK_CHECK",
        message="Risk passed",
        payload={"approved": True},
        prev_hash="a" * 64,
        hash="b" * 64
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
