"""End-to-End Integration Test for CYBER SWARM Pipeline"""
import pytest
from datetime import datetime, UTC

from cyber_swarm.agents.specialized_agents import create_swarm
from cyber_swarm.consensus.consensus_engine import ConsensusEngine
from cyber_swarm.risk.risk_gate import InstitutionalRiskGate
from cyber_swarm.execution.router import ExecutionRouter
from cyber_swarm.audit.ledger import ledger
from cyber_swarm.core.models import MarketTick, OrderStatus

@pytest.mark.asyncio
async def test_full_trading_pipeline_e2e():
    swarm = create_swarm()
    consensus_engine = ConsensusEngine()
    risk_gate = InstitutionalRiskGate()
    router = ExecutionRouter()

    tick = MarketTick(
        symbol="XAUUSD",
        price=2384.42,
        bid=2384.30,
        ask=2384.55,
        spread=0.25,
        volume_24h=28400000.0,
        change_pct=1.45,
        timestamp=datetime.now(UTC)
    )

    # 1. Swarm deliberation
    signals = []
    for _agent_id, agent in swarm.items():
        sig = await agent.evaluate(tick)
        signals.append(sig)
        assert sig.raw_aicl != ""

    assert len(signals) == 8

    # 2. Consensus aggregation
    consensus = consensus_engine.aggregate(signals, tick.symbol)
    assert consensus.participating_agents == list(swarm.keys())
    assert consensus.score > 0.50

    # 3. Risk Gate Evaluation
    risk_eval = risk_gate.evaluate_pre_trade(
        consensus=consensus,
        tick=tick,
        portfolio=router.portfolio,
        lot_size=0.10
    )
    assert risk_eval.approved is True

    # 4. Execution Router
    order = await router.execute_order(risk_eval, consensus, tick)
    assert order.status == OrderStatus.FILLED
    assert order.lot_size == 0.10
    assert order.fill_price is not None

    # 5. Audit Ledger record and verification
    record = ledger.record_event(
        source="VESKA",
        event_type="ORDER_FILLED",
        message=f"Order {order.order_id} filled @ {order.fill_price}",
        payload={"order_id": order.order_id, "symbol": tick.symbol}
    )
    assert record.index > 0
    assert ledger.verify_integrity() is True
