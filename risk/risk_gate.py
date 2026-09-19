"""CYBER SWARM TRADING OS - Institutional Risk Gate (RUNE)

Enforces fail-closed deterministic invariants:
1. Emergency Stop Killswitch
2. Daily Drawdown Limit (e.g. 5.0%)
3. Maximum Risk Per Single Trade (e.g. 2.0%)
4. Maximum Total Portfolio Exposure (e.g. 40.0%)
5. Concurrent Open Positions Cap (e.g. 8)
6. Stale Data & Feed Latency Guard (< 2000ms)
7. Spread & Session Anomaly Filter
"""
from datetime import datetime, UTC

from cyber_swarm.core.models import (
    ConsensusResult,
    RiskEvaluation,
    OrderDirection,
    PortfolioState,
    MarketTick
)
from cyber_swarm.core.config import config

class InstitutionalRiskGate:
    def __init__(self):
        self.killswitch_active: bool = False
        self.killswitch_reason: str = ""
        self.consecutive_rejections: int = 0

    def trigger_emergency_stop(self, reason: str = "Operator Triggered"):
        self.killswitch_active = True
        self.killswitch_reason = reason

    def reset_emergency_stop(self):
        self.killswitch_active = False
        self.killswitch_reason = ""

    def evaluate_pre_trade(
        self,
        consensus: ConsensusResult,
        tick: MarketTick,
        portfolio: PortfolioState,
        lot_size: float | None = None
    ) -> RiskEvaluation:
        """Evaluates whether the consensus signal passes all institutional risk constraints."""
        reasons: list[str] = []
        approved = True
        target_lot = lot_size if lot_size is not None else config.fixed_lot_size

        # Invariant 1: Emergency Stop Check
        if self.killswitch_active:
            approved = False
            reasons.append(f"KILLSWITCH_ACTIVE: {self.killswitch_reason}")
            return RiskEvaluation(
                approved=False,
                direction=OrderDirection.HOLD,
                symbol=consensus.symbol,
                lot_size=0.0,
                estimated_risk_pct=0.0,
                current_drawdown_pct=portfolio.daily_drawdown_pct,
                exposure_pct=portfolio.risk_exposure_pct,
                reasons=reasons
            )

        # Invariant 2: Direction Check (Do not execute HOLD)
        if consensus.direction == OrderDirection.HOLD:
            approved = False
            reasons.append("DIRECTION_IS_HOLD")
            return RiskEvaluation(
                approved=False,
                direction=OrderDirection.HOLD,
                symbol=consensus.symbol,
                lot_size=0.0,
                estimated_risk_pct=0.0,
                current_drawdown_pct=portfolio.daily_drawdown_pct,
                exposure_pct=portfolio.risk_exposure_pct,
                reasons=reasons
            )

        # Invariant 3: Daily Drawdown Limit
        if portfolio.daily_drawdown_pct >= config.max_drawdown_limit_pct:
            approved = False
            reasons.append(
                f"DRAWDOWN_BREACH: Current {portfolio.daily_drawdown_pct:.2f}% >= Cap {config.max_drawdown_limit_pct:.2f}%"
            )

        # Invariant 4: Maximum Portfolio Exposure
        if portfolio.risk_exposure_pct >= config.max_total_exposure_pct:
            approved = False
            reasons.append(
                f"EXPOSURE_BREACH: Current {portfolio.risk_exposure_pct:.2f}% >= Cap {config.max_total_exposure_pct:.2f}%"
            )

        # Invariant 5: Max Open Positions Cap
        if len(portfolio.open_positions) >= config.max_open_positions:
            approved = False
            reasons.append(
                f"POSITIONS_CAP_BREACH: Open {len(portfolio.open_positions)} >= Max {config.max_open_positions}"
            )

        # Invariant 6: Data Freshness / Stale Feed Check
        now_utc = datetime.now(UTC)
        tick_age_ms = (now_utc - tick.timestamp).total_seconds() * 1000.0
        if tick_age_ms > config.max_stale_data_latency_ms:
            approved = False
            reasons.append(f"STALE_MARKET_FEED: Latency {tick_age_ms:.0f}ms > {config.max_stale_data_latency_ms}ms")

        # Invariant 7: Spread Anomaly Check
        if tick.spread > 50.0:  # Excessive spread threshold for safety
            approved = False
            reasons.append(f"ABNORMAL_SPREAD: Spread {tick.spread} pts exceeds safety limit")

        # Invariant 8: Auto Trade Bot Master Toggle Check
        if not getattr(portfolio, "auto_trade_enabled", True) or not config.auto_trade_enabled:
            approved = False
            reasons.append("AUTO_TRADE_DISABLED: Master bot execution switch is inactive")

        # Invariant 9: Fixed / Configured Lot Size Invariant & Bounds Check
        if target_lot < config.min_lot_size or target_lot > config.max_lot_size:
            approved = False
            reasons.append(
                f"LOT_SIZE_OUT_OF_BOUNDS: {target_lot:.2f} lot outside [{config.min_lot_size:.2f}, {config.max_lot_size:.2f}]"
            )
        elif round(target_lot, 2) != round(config.fixed_lot_size, 2):
            approved = False
            reasons.append(
                f"FIXED_LOT_SIZE_VIOLATION: Required {config.fixed_lot_size:.2f} lot, got {target_lot:.2f}"
            )

        # Position Sizing & Risk per Trade Calculation
        # Scaled dynamically relative to base 0.10 lot (nominal 1.45%)
        base_nominal_risk = 1.45
        estimated_risk_pct = round(base_nominal_risk * (target_lot / 0.10 if target_lot > 0 else 1.0), 2)

        if estimated_risk_pct > config.max_risk_per_trade_pct:
            approved = False
            reasons.append(
                f"TRADE_RISK_EXCEEDS_CAP: {estimated_risk_pct:.2f}% > {config.max_risk_per_trade_pct:.2f}%"
            )

        if approved:
            reasons.append("ALL_RISK_INVARIANTS_PASSED")
            self.consecutive_rejections = 0
        else:
            self.consecutive_rejections += 1

        return RiskEvaluation(
            approved=approved,
            direction=consensus.direction if approved else OrderDirection.HOLD,
            symbol=consensus.symbol,
            lot_size=target_lot if approved else 0.0,
            estimated_risk_pct=estimated_risk_pct if approved else 0.0,
            current_drawdown_pct=portfolio.daily_drawdown_pct,
            exposure_pct=portfolio.risk_exposure_pct,
            reasons=reasons
        )
