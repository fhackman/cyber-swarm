"""CYBER SWARM TRADING OS - Base Agent Class"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import time
from typing import Dict, Any, List, Optional
import logging

from cyber_swarm.core.models import AgentSignal, OrderDirection, MarketTick
from cyber_swarm.core.aicl import AICLMessage

logger = logging.getLogger("cyber_swarm.agent")

class BaseSwarmAgent(ABC):
    def __init__(
        self,
        agent_id: str,
        role: str,
        weight: float = 1.0,
        reliability: float = 0.95,
        version: str = "v1.0.0"
    ):
        self.agent_id = agent_id.upper()
        self.role = role
        self.weight = weight
        self.reliability = reliability
        self.version = version
        self.status = "SYNCED"  # SYNCED, PROCESSING, IDLE, DEGRADED
        self.last_latency_ms: float = 0.0
        self.last_heartbeat = datetime.now(timezone.utc)
        self.total_evaluations: int = 0
        self.memory: Dict[str, Any] = {}

    @abstractmethod
    async def evaluate(self, tick: MarketTick, context_data: Optional[Dict[str, Any]] = None) -> AgentSignal:
        """Evaluates market conditions and produces a typed AgentSignal."""
        pass

    def to_aicl_signal(self, signal: AgentSignal) -> str:
        """Converts an AgentSignal into a canonical AICL compact protocol message."""
        msg = AICLMessage(
            action="SET",
            source=self.agent_id,
            destination="ORC",
            context="TRD+SWARM",
            objective="SIG",
            constraints="P0=RISK;P1=SIG",
            data={
                "sym": signal.symbol,
                "dir": signal.direction.value,
                "cf": round(signal.confidence, 4),
                "w": round(signal.weight, 2),
                "rel": round(signal.reliability, 2),
                "evd": "+".join(signal.evidence) if signal.evidence else "NONE"
            },
            output_format="VOTE",
            state="RDY"
        )
        return msg.encode()

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns the real-time node telemetry dictionary."""
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "weight": self.weight,
            "reliability": self.reliability,
            "status": self.status,
            "latency_ms": round(self.last_latency_ms, 2),
            "version": self.version,
            "last_heartbeat": self.last_heartbeat.isoformat()
        }
