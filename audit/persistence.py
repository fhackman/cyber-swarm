"""CYBER SWARM TRADING OS - Cryptographic Audit Persistence Engine (MARIN)

Stores the immutable SHA-256 hash-chain audit trail and trade orders in SQLite,
enabling persistent recovery and tamper-detection verification across restarts.
"""
import sqlite3
import json
import hashlib
import logging
from pathlib import Path

from cyber_swarm.audit.ledger import AuditRecord
from cyber_swarm.core.models import TradeOrder

logger = logging.getLogger("cyber_swarm.persistence")
DEFAULT_DB_PATH = Path(__file__).parent / "audit_store.db"

class AuditPersistence:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(str(self.db_path), timeout=30.0) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA busy_timeout=5000;")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS audit_records (
                    record_index INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    hash TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_orders (
                    order_id TEXT PRIMARY KEY,
                    cycle_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    lot_size REAL NOT NULL,
                    target_price REAL NOT NULL,
                    fill_price REAL,
                    slippage_bps REAL,
                    status TEXT NOT NULL,
                    decision_trace_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Failed to initialize SQLite audit store: {e}")

    def persist_record(self, record: AuditRecord):
        try:
            with sqlite3.connect(str(self.db_path), timeout=30.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO audit_records
                    (record_index, timestamp, source, event_type, message, payload_json, prev_hash, hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.index,
                    record.timestamp,
                    record.source,
                    record.event_type,
                    record.message,
                    json.dumps(record.payload, sort_keys=True),
                    record.prev_hash,
                    record.hash
                ))
                conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Failed to persist audit record {record.index}: {e}")

    def load_all_records(self, limit: int | None = None) -> list[AuditRecord]:
        records = []
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            cursor = conn.cursor()
            if limit is not None:
                cursor.execute("""
                    SELECT record_index, timestamp, source, event_type, message, payload_json, prev_hash, hash
                    FROM (
                        SELECT record_index, timestamp, source, event_type, message, payload_json, prev_hash, hash
                        FROM audit_records ORDER BY record_index DESC LIMIT ?
                    ) ORDER BY record_index ASC
                """, (limit,))
            else:
                cursor.execute("""
                    SELECT record_index, timestamp, source, event_type, message, payload_json, prev_hash, hash
                    FROM audit_records ORDER BY record_index ASC
                """)
            for row in cursor.fetchall():
                records.append(AuditRecord(
                    index=row[0],
                    timestamp=row[1],
                    source=row[2],
                    event_type=row[3],
                    message=row[4],
                    payload=json.loads(row[5]),
                    prev_hash=row[6],
                    hash=row[7]
                ))
        except sqlite3.Error as e:
            logger.warning(f"Failed to load audit records: {e}")
        finally:
            if conn:
                conn.close()
        return records

    def persist_order(self, order: TradeOrder):
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO trade_orders
                (order_id, cycle_id, symbol, direction, lot_size, target_price, fill_price, slippage_bps, status, decision_trace_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id,
                order.cycle_id,
                order.symbol,
                order.direction.value,
                order.lot_size,
                order.target_price,
                order.fill_price,
                order.slippage_bps,
                order.status.value,
                json.dumps(order.decision_trace),
                order.timestamp.isoformat()
            ))
            conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Failed to persist trade order {order.order_id}: {e}")
        finally:
            if conn:
                conn.close()

    def verify_stored_integrity(self, limit: int | None = 100) -> bool:
        """Verifies cryptographic hash chain and block payload integrity of recent records in SQLite."""
        records = self.load_all_records(limit=limit)
        if len(records) < 2:
            return True
        for i in range(1, len(records)):
            curr = records[i]
            prev = records[i - 1]
            if curr.prev_hash != prev.hash:
                return False
            block_content = f"{curr.index}{curr.timestamp}{curr.source}{curr.event_type}{curr.message}{json.dumps(curr.payload, sort_keys=True)}{prev.hash}"
            if hashlib.sha256(block_content.encode()).hexdigest() != curr.hash:
                return False
        return True

# Global persistence instance
audit_db = AuditPersistence()
