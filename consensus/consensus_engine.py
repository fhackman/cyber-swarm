"""CYBER SWARM TRADING OS - Multi-Factor Consensus Engine

Aggregates heterogeneous agent votes using reliability and conviction weighting:
    Consensus = Σ(weight × confidence × reliability × direction_scalar) / Σ(weight)
"""
from cyber_swarm.core.models import (
    AgentSignal,
    ConsensusResult,
    ConsensusState,
    OrderDirection
)
from cyber_swarm.core.config import config

class ConsensusEngine:
    def __init__(self):
        self.cycle_counter = 84209

    def aggregate(self, signals: list[AgentSignal], symbol: str) -> ConsensusResult:
        self.cycle_counter += 1
        if not signals:
            return ConsensusResult(
                cycle_id=self.cycle_counter,
                symbol=symbol,
                direction=OrderDirection.HOLD,
                score=0.0,
                state=ConsensusState.HOLD,
                participating_agents=[],
                votes={},
                evidence_chain=["no_signals_provided"]
            )

        total_weight = 0.0
        weighted_direction_score = 0.0
        participating_agents = []
        votes = {}
        all_evidence = []

        buy_weight = 0.0
        sell_weight = 0.0
        hold_weight = 0.0

        for sig in signals:
            participating_agents.append(sig.agent_id)
            effective_weight = sig.weight * sig.reliability
            total_weight += effective_weight

            scalar = 0.0
            if sig.direction == OrderDirection.BUY:
                scalar = 1.0
                buy_weight += effective_weight * sig.confidence
            elif sig.direction == OrderDirection.SELL:
                scalar = -1.0
                sell_weight += effective_weight * sig.confidence
            else:
                hold_weight += effective_weight * (1.0 - sig.confidence)

            weighted_direction_score += effective_weight * sig.confidence * scalar

            votes[sig.agent_id] = {
                "direction": sig.direction.value,
                "confidence": round(sig.confidence, 4),
                "weight": round(sig.weight, 2),
                "reliability": round(sig.reliability, 2),
                "evidence": sig.evidence
            }
            all_evidence.extend([f"{sig.agent_id}:{ev}" for ev in sig.evidence])

        # Determine dominant direction
        if buy_weight > sell_weight and buy_weight > hold_weight:
            direction = OrderDirection.BUY
            raw_conviction = buy_weight / total_weight if total_weight > 0 else 0.0
        elif sell_weight > buy_weight and sell_weight > hold_weight:
            direction = OrderDirection.SELL
            raw_conviction = sell_weight / total_weight if total_weight > 0 else 0.0
        else:
            direction = OrderDirection.HOLD
            raw_conviction = hold_weight / total_weight if total_weight > 0 else 0.0

        # Map to ConsensusState thresholds
        if raw_conviction < config.consensus_hold_max:
            state = ConsensusState.HOLD
            direction = OrderDirection.HOLD
        elif raw_conviction < config.consensus_watch_max:
            state = ConsensusState.WATCH
        elif raw_conviction < config.consensus_high_conviction_min:
            state = ConsensusState.SIGNAL
        elif raw_conviction < config.consensus_extreme_min:
            state = ConsensusState.HIGH_CONFIDENCE
        else:
            state = ConsensusState.EXTREME_CONSENSUS

        return ConsensusResult(
            cycle_id=self.cycle_counter,
            symbol=symbol,
            direction=direction,
            score=round(raw_conviction, 4),
            state=state,
            participating_agents=participating_agents,
            votes=votes,
            evidence_chain=list(dict.fromkeys(all_evidence))  # Deduplicate while preserving order
        )
