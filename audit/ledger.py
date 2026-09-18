"""CYBER SWARM TRADING OS - Cryptographic Immutable Audit Ledger (MARIN)"""
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AuditRecord(BaseModel):
    index: int
    timestamp: str
    event_type: str
    source: str
    message: str
    payload: Dict[str, Any]
    prev_hash: str
    hash: str

class ImmutableAuditLedger:
    def __init__(self):
        self.records: List[AuditRecord] = []
        self._genesis()

    def _genesis(self):
        genesis_payload = {"system": "CYBER_SWARM_OS", "version": "v2.4.19-PROD"}
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        h = hashlib.sha256(json.dumps(genesis_payload, sort_keys=True).encode()).hexdigest()
        self.records.append(
            AuditRecord(
                index=0,
                timestamp=ts,
                event_type="GENESIS",
                source="SYSTEM",
                message="Cyber Swarm OS Initialized. Audit chain started.",
                payload=genesis_payload,
                prev_hash="0" * 64,
                hash=h
            )
        )
        self._seed_recent_timeline()

    def _seed_recent_timeline(self):
        events = [
            ("TIDAL", "SIGNAL", "TIDAL detected liquidity sweep on XAUUSD M15", {"sym": "XAUUSD", "cf": 0.924}),
            ("NORO", "SIGNAL", "NORO confirmed bearish exhaustion 78% in premium zone", {"sym": "XAUUSD", "cf": 0.78}),
            ("LUMEN", "REGIME", "LUMEN neutral 52% (Macro disconnect balanced)", {"sym": "XAUUSD", "cf": 0.52}),
            ("ZEPHR", "MICROSTRUCTURE", "ZEPHR sell-side liquidity confirmed with +3.2 book skew", {"sym": "XAUUSD", "cf": 0.881}),
            ("RUNE", "RISK_GATE", "RUNE pre-trade risk evaluated: Invariants PASSED", {"approved": True, "risk_pct": 1.45}),
            ("CONSENSUS", "VOTE", "Consensus reached: 81.4% SELL on XAUUSD", {"conviction": 0.814, "dir": "SELL"}),
            ("VESKA", "EXECUTION", "VESKA submitted smart routed limit order", {"order_id": "ORD-E8391A", "lot": 1.5}),
            ("MARIN", "SETTLEMENT", "MARIN confirmed fill @ 2384.42, slippage 0.4 bps", {"status": "FILLED", "fill": 2384.42})
        ]
        for src, etype, msg, payload in events:
            self.record_event(src, etype, msg, payload)

    def record_event(self, source: str, event_type: str, message: str, payload: Optional[Dict[str, Any]] = None) -> AuditRecord:
        payload = payload or {}
        last_rec = self.records[-1]
        new_idx = last_rec.index + 1
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        
        block_content = f"{new_idx}{ts}{source}{event_type}{message}{json.dumps(payload, sort_keys=True)}{last_rec.hash}"
        new_hash = hashlib.sha256(block_content.encode()).hexdigest()
        
        record = AuditRecord(
            index=new_idx,
            timestamp=ts,
            event_type=event_type,
            source=source,
            message=message,
            payload=payload,
            prev_hash=last_rec.hash,
            hash=new_hash
        )
        self.records.append(record)
        return record

    def get_recent(self, limit: int = 50) -> List[AuditRecord]:
        return self.records[-limit:]

    def verify_integrity(self) -> bool:
        """Verifies cryptographic hash chain integrity."""
        for i in range(1, len(self.records)):
            curr = self.records[i]
            prev = self.records[i - 1]
            if curr.prev_hash != prev.hash:
                return False
            block_content = f"{curr.index}{curr.timestamp}{curr.source}{curr.event_type}{curr.message}{json.dumps(curr.payload, sort_keys=True)}{prev.hash}"
            if hashlib.sha256(block_content.encode()).hexdigest() != curr.hash:
                return False
        return True

# Global singleton ledger
ledger = ImmutableAuditLedger()
