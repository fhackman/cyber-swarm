"""Tests for Institutional Risk Gate (RUNE) Invariants"""
import pytest
from datetime import datetime, timezone, timedelta

from cyber_swarm.risk.risk_gate import InstitutionalRiskGate
from cyber_swarm.core.models import (
    ConsensusResult,
    ConsensusState,
    OrderDirection,
    PortfolioState,
    MarketTick,
    Position
)
from cyber_swarm.core.config import config

@pytest.fixture
def risk_gate():
    return InstitutionalRiskGate()

@pytest.fixture
def base_portfolio():
    return PortfolioState(
        net_equity=100000.0,
        realized_pnl_mtd=5000.0,
        unrealized_pnl=1000.0,
        daily_drawdown_pct=1.5,
        max_drawdown_pct=2.0,
        risk_exposure_pct=15.0,
        win_rate_pct=70.0,
        total_trades=50,
        volume_24h_usd=1000000.0,
        open_positions=[]
    )

@pytest.fixture
def sample_tick():
    return MarketTick(
        symbol="XAUUSD",
        price=2384.42,
        bid=2384.30,
        ask=2384.55,
        spread=0.25,
        volume_24h=50000.0,
        change_pct=0.84,
        timestamp=datetime.now(timezone.utc)
    )

@pytest.fixture
def sample_consensus():
    return ConsensusResult(
        cycle_id=100,
        symbol="XAUUSD",
        direction=OrderDirection.SELL,
        score=0.85,
        state=ConsensusState.HIGH_CONFIDENCE,
        participating_agents=["TIDAL", "NORO"],
        votes={},
        evidence_chain=["sweep"]
    )

def test_risk_gate_approves_valid_signal(risk_gate, sample_consensus, sample_tick, base_portfolio):
    eval_res = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio, lot_size=0.10)
    assert eval_res.approved is True
    assert eval_res.direction == OrderDirection.SELL
    assert eval_res.lot_size == 0.10
    assert "ALL_RISK_INVARIANTS_PASSED" in eval_res.reasons

def test_risk_gate_rejects_on_killswitch(risk_gate, sample_consensus, sample_tick, base_portfolio):
    risk_gate.trigger_emergency_stop("Operator Manual Halt")
    eval_res = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio)
    assert eval_res.approved is False
    assert any("KILLSWITCH_ACTIVE" in r for r in eval_res.reasons)

def test_risk_gate_rejects_on_max_drawdown_breach(risk_gate, sample_consensus, sample_tick, base_portfolio):
    base_portfolio.daily_drawdown_pct = 5.5  # Breaches 5.0%
    eval_res = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio)
    assert eval_res.approved is False
    assert any("DRAWDOWN_BREACH" in r for r in eval_res.reasons)

def test_risk_gate_rejects_stale_feed(risk_gate, sample_consensus, sample_tick, base_portfolio):
    sample_tick.timestamp = datetime.now(timezone.utc) - timedelta(seconds=5)  # 5000ms > 2000ms
    eval_res = risk_gate.evaluate_pre_trade(sample_consensus, sample_tick, base_portfolio)
    assert eval_res.approved is False
    assert any("STALE_MARKET_FEED" in r for r in eval_res.reasons)
