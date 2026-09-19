"""Tests for Consensus Engine Aggregation"""
from cyber_swarm.consensus.consensus_engine import ConsensusEngine
from cyber_swarm.core.models import AgentSignal, OrderDirection, ConsensusState

def test_consensus_unanimous_sell():
    engine = ConsensusEngine()
    signals = [
        AgentSignal(agent_id="TIDAL", symbol="XAUUSD", direction=OrderDirection.SELL, confidence=0.92, weight=1.3, reliability=0.98),
        AgentSignal(agent_id="ZEPHR", symbol="XAUUSD", direction=OrderDirection.SELL, confidence=0.88, weight=1.2, reliability=0.95),
        AgentSignal(agent_id="NORO", symbol="XAUUSD", direction=OrderDirection.SELL, confidence=0.85, weight=1.1, reliability=0.96)
    ]
    res = engine.aggregate(signals, "XAUUSD")
    assert res.direction == OrderDirection.SELL
    assert res.score >= 0.80
    assert res.state in [ConsensusState.HIGH_CONFIDENCE, ConsensusState.EXTREME_CONSENSUS]
    assert len(res.participating_agents) == 3

def test_consensus_conflicting_signals_defaults_hold():
    engine = ConsensusEngine()
    signals = [
        AgentSignal(agent_id="TIDAL", symbol="EURUSD", direction=OrderDirection.BUY, confidence=0.60, weight=1.0, reliability=0.90),
        AgentSignal(agent_id="NORO", symbol="EURUSD", direction=OrderDirection.SELL, confidence=0.62, weight=1.0, reliability=0.90)
    ]
    res = engine.aggregate(signals, "EURUSD")
    # Due to low conviction/conflict, should fall under hold threshold or watch
    assert res.score < 0.70
    assert res.state in [ConsensusState.HOLD, ConsensusState.WATCH]
