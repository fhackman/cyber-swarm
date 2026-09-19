"""CYBER SWARM TRADING OS - Smart Order Execution Router (VESKA)"""
import uuid
from datetime import datetime, UTC
from typing import Any
import logging

from cyber_swarm.core.models import (
    TradeOrder,
    OrderStatus,
    OrderDirection,
    OrderType,
    RiskEvaluation,
    ConsensusResult,
    Position,
    PortfolioState,
    MarketTick,
    NetworkStatus,
    ReconciliationAction,
    ReconciliationRecord,
    ReconciliationReport
)
from cyber_swarm.core.config import config

logger = logging.getLogger("cyber_swarm.router")

class ExecutionRouter:
    def __init__(self):
        self.orders: dict[str, TradeOrder] = {}
        self.pending_orders: dict[str, TradeOrder] = {}
        self.active_positions: dict[str, Position] = {}
        self.portfolio = PortfolioState(
            net_equity=config.initial_equity,
            realized_pnl_mtd=142390.00,
            unrealized_pnl=18450.20,
            daily_drawdown_pct=2.14,
            max_drawdown_pct=2.85,
            risk_exposure_pct=18.6,
            win_rate_pct=74.2,
            total_trades=184,
            volume_24h_usd=28400000.0,
            auto_trade_enabled=config.auto_trade_enabled,
            lot_size=config.fixed_lot_size,
            min_lot_size=config.min_lot_size,
            max_lot_size=config.max_lot_size,
            lot_step=config.lot_step,
            lot_presets=config.lot_presets,
            open_positions=[],
            pending_orders=[],
            uptime_pct=99.98,
            active_cycle=84209
        )
        self._init_sample_positions()

    def _init_sample_positions(self):
        # Initialize the 4 active positions mentioned in Stitch dashboard
        pos1 = Position(
            position_id="POS-01",
            symbol="XAUUSD",
            direction=OrderDirection.SELL,
            lot_size=1.5,
            entry_price=2389.20,
            current_price=2384.42,
            unrealized_pnl=7170.00
        )
        pos2 = Position(
            position_id="POS-02",
            symbol="BTCUSD",
            direction=OrderDirection.BUY,
            lot_size=0.5,
            entry_price=66800.00,
            current_price=67412.10,
            unrealized_pnl=3060.50
        )
        pos3 = Position(
            position_id="POS-03",
            symbol="EURUSD",
            direction=OrderDirection.BUY,
            lot_size=5.0,
            entry_price=1.0850,
            current_price=1.0894,
            unrealized_pnl=2200.00
        )
        pos4 = Position(
            position_id="POS-04",
            symbol="USOIL",
            direction=OrderDirection.BUY,
            lot_size=3.0,
            entry_price=79.24,
            current_price=81.24,
            unrealized_pnl=6000.00
        )
        for p in [pos1, pos2, pos3, pos4]:
            self.active_positions[p.position_id] = p
        self.portfolio.open_positions = list(self.active_positions.values())

    def calculate_take_profit(
        self,
        symbol: str,
        direction: OrderDirection,
        entry_price: float,
        points: int | None = None
    ) -> float:
        """Calculates Take Profit price target based on point calibration (100 - 300 points)."""
        tp_pts = points if points is not None else config.take_profit_points
        tp_pts = max(config.take_profit_points_min, min(config.take_profit_points_max, tp_pts))

        pt_size = config.point_sizes.get(symbol, 0.01)
        delta = tp_pts * pt_size
        decimals = 5 if symbol == "EURUSD" else 2

        if direction == OrderDirection.BUY:
            return round(entry_price + delta, decimals)
        else:
            return round(entry_price - delta, decimals)

    async def execute_order(
        self,
        risk_eval: RiskEvaluation,
        consensus: ConsensusResult,
        tick: MarketTick
    ) -> TradeOrder:
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

        trace = [
            f"Consensus achieved: {consensus.score*100:.1f}% {consensus.direction.value}",
            f"Risk Gate Approved: lot={risk_eval.lot_size} risk={risk_eval.estimated_risk_pct:.2f}%",
            f"Mode: {config.mode.value}"
        ]

        if not risk_eval.approved:
            order = TradeOrder(
                order_id=order_id,
                cycle_id=consensus.cycle_id,
                symbol=consensus.symbol,
                direction=consensus.direction,
                lot_size=0.0,
                target_price=tick.price,
                status=OrderStatus.REJECTED,
                decision_trace=trace + [f"Rejected by Risk Gate: {', '.join(risk_eval.reasons)}"]
            )
            self.orders[order_id] = order
            return order

        # Enforce fixed 0.10 lot size
        lot_size = config.fixed_lot_size

        # Fill order based on mode
        fill_price = tick.ask if risk_eval.direction == OrderDirection.BUY else tick.bid
        slippage_bps = 0.4  # Micro slippage in simulation

        # Calculate take profit if enabled
        tp_price = None
        tp_pts = None
        if config.take_profit_enabled:
            tp_pts = config.take_profit_points
            tp_price = self.calculate_take_profit(consensus.symbol, risk_eval.direction, fill_price, tp_pts)

        order = TradeOrder(
            order_id=order_id,
            cycle_id=consensus.cycle_id,
            symbol=consensus.symbol,
            direction=risk_eval.direction,
            order_type=OrderType.MARKET,
            lot_size=lot_size,
            target_price=tick.price,
            fill_price=fill_price,
            take_profit=tp_price,
            take_profit_points=tp_pts,
            slippage_bps=slippage_bps,
            status=OrderStatus.FILLED,
            decision_trace=trace + [f"Filled at {fill_price:.4f} with {slippage_bps} bps slippage (TP: {tp_price})"]
        )
        self.orders[order_id] = order

        # Create or update position with trailing stop and take profit settings
        pos_id = f"POS-{consensus.symbol}-{order.order_id[-4:]}"
        profile = config.trailing_stop_profiles.get(consensus.symbol, {"activation_delta": 4.0, "trail_distance": 8.0})
        new_pos = Position(
            position_id=pos_id,
            symbol=consensus.symbol,
            direction=risk_eval.direction,
            lot_size=lot_size,
            entry_price=fill_price,
            current_price=tick.price,
            take_profit=tp_price,
            take_profit_points=tp_pts,
            trailing_active=config.trailing_stop_enabled,
            trail_distance=profile.get("trail_distance", 8.0),
            trail_activation_delta=profile.get("activation_delta", 4.0),
            highest_price=fill_price,
            lowest_price=fill_price,
            unrealized_pnl=0.0
        )
        self.active_positions[pos_id] = new_pos
        self.portfolio.open_positions = list(self.active_positions.values())
        self.portfolio.total_trades += 1

        return order

    def create_pending_limit_order(
        self,
        symbol: str,
        direction: OrderDirection,
        order_type: OrderType,
        limit_price: float,
        cycle_id: int | str = 0,
        take_profit_points: int | None = None,
        lot_size: float | None = None
    ) -> TradeOrder:
        """Creates and tracks a pending limit order with adjustable lot size and auto take profit."""
        if lot_size is None:
            lot_size = config.fixed_lot_size
        else:
            lot_size = max(config.min_lot_size, min(config.max_lot_size, round(lot_size, 2)))
        order_id = f"LMT-{uuid.uuid4().hex[:8].upper()}"

        tp_price = None
        tp_pts = None
        if config.take_profit_enabled or take_profit_points is not None:
            tp_pts = take_profit_points if take_profit_points is not None else config.take_profit_points
            tp_price = self.calculate_take_profit(symbol, direction, limit_price, tp_pts)

        order = TradeOrder(
            order_id=order_id,
            cycle_id=cycle_id,
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            lot_size=lot_size,
            target_price=limit_price,
            limit_price=limit_price,
            take_profit=tp_price,
            take_profit_points=tp_pts,
            status=OrderStatus.PENDING,
            decision_trace=[f"Auto Limit Order: {order_type.value} {lot_size:.2f} lot @ {limit_price:.4f} (TP: {tp_price})"]
        )
        self.pending_orders[order_id] = order
        self.orders[order_id] = order
        self.portfolio.pending_orders = list(self.pending_orders.values())
        logger.info(f"Created pending limit order: {order_id} {order_type.value} {symbol} @ {limit_price} (TP: {tp_price})")
        return order

    def check_pending_orders(self, tick: MarketTick) -> list[TradeOrder]:
        """Checks pending limit orders against current tick; fills orders when price touches limit."""
        filled_orders = []
        for order_id, order in list(self.pending_orders.items()):
            if order.symbol != tick.symbol:
                continue

            should_fill = False
            fill_price = order.target_price

            if order.order_type == OrderType.BUY_LIMIT and (tick.ask <= order.target_price or tick.price <= order.target_price):
                should_fill = True
                fill_price = tick.ask
            elif order.order_type == OrderType.SELL_LIMIT and (tick.bid >= order.target_price or tick.price >= order.target_price):
                should_fill = True
                fill_price = tick.bid

            if should_fill:
                order.status = OrderStatus.FILLED
                order.fill_price = fill_price
                order.decision_trace.append(f"Limit executed @ {fill_price:.4f}")
                del self.pending_orders[order_id]

                pos_id = f"POS-{order.symbol}-{order.order_id[-4:]}"
                profile = config.trailing_stop_profiles.get(order.symbol, {"activation_delta": 4.0, "trail_distance": 8.0})
                new_pos = Position(
                    position_id=pos_id,
                    symbol=order.symbol,
                    direction=order.direction,
                    lot_size=order.lot_size,
                    entry_price=fill_price,
                    current_price=tick.price,
                    take_profit=order.take_profit,
                    take_profit_points=order.take_profit_points,
                    trailing_active=config.trailing_stop_enabled,
                    trail_distance=profile.get("trail_distance", 8.0),
                    trail_activation_delta=profile.get("activation_delta", 4.0),
                    highest_price=fill_price,
                    lowest_price=fill_price,
                    unrealized_pnl=0.0
                )
                self.active_positions[pos_id] = new_pos
                self.portfolio.total_trades += 1
                filled_orders.append(order)
                logger.info(f"Pending limit filled: {order_id} {order.direction.value} @ {fill_price}")

        self.portfolio.pending_orders = list(self.pending_orders.values())
        self.portfolio.open_positions = list(self.active_positions.values())
        return filled_orders

    def cancel_pending_order(self, order_id: str) -> TradeOrder | None:
        """Cancels an active pending limit order."""
        if order_id in self.pending_orders:
            order = self.pending_orders.pop(order_id)
            order.status = OrderStatus.CANCELLED
            self.portfolio.pending_orders = list(self.pending_orders.values())
            logger.info(f"Cancelled pending order: {order_id}")
            return order
        return None

    def reconcile_pending_orders(
        self,
        current_ticks: dict[str, MarketTick],
        current_consensus: dict[str, ConsensusResult] | None = None,
        mt5_orders: list[Any] | None = None,
        downtime_seconds: float = 0.0
    ) -> ReconciliationReport:
        """
        Post-reconnection order reconciliation engine.
        Reviews all active pending limit orders across 5 invariant conditions:
          1. Broker Terminal Synchronization (check if filled during downtime -> adopt as active position)
          2. Stale Order TTL / Outage Age (cancel if order age or downtime exceeds max TTL)
          3. Institutional Risk Invariants (fixed lot 0.10, take profit within 100-300 points)
          4. Swarm Directional Alignment (cancel if swarm consensus reversed >= 70% in opposite direction)
          5. Price Validity & Gap Inversion (BUY_LIMIT <= ask/market, SELL_LIMIT >= bid/market without fill -> cancel)
        """
        now = datetime.now(UTC)
        records: list[ReconciliationRecord] = []
        retained_count = 0
        cancelled_count = 0
        filled_count = 0
        total_reviewed = len(self.pending_orders)

        for order_id, order in list(self.pending_orders.items()):
            symbol = order.symbol
            tick = current_ticks.get(symbol)
            limit_price = order.limit_price or order.target_price
            market_price = tick.price if tick else limit_price
            cons = current_consensus.get(symbol) if current_consensus else None
            cons_score = cons.score if cons else None

            # Condition 5 / Broker check: Check if filled on MT5 broker during disconnect
            is_filled_on_broker = False
            if mt5_orders:
                for mo in mt5_orders:
                    if isinstance(mo, str) and mo == order_id:
                        is_filled_on_broker = True
                        break
                    elif hasattr(mo, "order_id") and mo.order_id == order_id:
                        if getattr(mo, "status", None) in (OrderStatus.FILLED, "FILLED"):
                            is_filled_on_broker = True
                            break
                    elif isinstance(mo, dict) and mo.get("order_id") == order_id:
                        if mo.get("status") in (OrderStatus.FILLED, "FILLED"):
                            is_filled_on_broker = True
                            break

            if is_filled_on_broker:
                # Adopt order as active position with TP and Trailing Stop
                order.status = OrderStatus.FILLED
                order.fill_price = limit_price
                order.decision_trace.append(f"Reconciliation: Adopted broker fill @ {limit_price}")
                del self.pending_orders[order_id]

                pos_id = f"POS-{order.symbol}-{order.order_id[-4:]}"
                profile = config.trailing_stop_profiles.get(order.symbol, {"activation_delta": 4.0, "trail_distance": 8.0})
                new_pos = Position(
                    position_id=pos_id,
                    symbol=order.symbol,
                    direction=order.direction,
                    lot_size=order.lot_size,
                    entry_price=limit_price,
                    current_price=market_price,
                    take_profit=order.take_profit,
                    take_profit_points=order.take_profit_points,
                    trailing_active=config.trailing_stop_enabled,
                    trail_distance=profile.get("trail_distance", 8.0),
                    trail_activation_delta=profile.get("activation_delta", 4.0),
                    highest_price=max(limit_price, market_price),
                    lowest_price=min(limit_price, market_price),
                    unrealized_pnl=0.0
                )
                self.active_positions[pos_id] = new_pos
                self.portfolio.total_trades += 1
                filled_count += 1
                records.append(ReconciliationRecord(
                    order_id=order_id,
                    symbol=symbol,
                    direction=order.direction,
                    order_type=order.order_type,
                    limit_price=limit_price,
                    action=ReconciliationAction.ADOPT_FILLED,
                    reason="ORDER_FILLED_BY_BROKER_DURING_DOWNTIME",
                    market_price=market_price,
                    consensus_score=cons_score,
                    timestamp=now
                ))
                continue

            # Condition 4: Stale TTL / Outage Age
            order_age_sec = (now - order.timestamp).total_seconds() if order.timestamp else 0.0
            if order_age_sec > config.max_pending_order_ttl_seconds or downtime_seconds > config.max_pending_order_ttl_seconds:
                order.status = OrderStatus.CANCELLED
                reason = f"ORDER_TTL_EXPIRED: age={order_age_sec:.0f}s downtime={downtime_seconds:.0f}s > {config.max_pending_order_ttl_seconds}s"
                order.decision_trace.append(f"Reconciliation Cancel: {reason}")
                del self.pending_orders[order_id]
                cancelled_count += 1
                records.append(ReconciliationRecord(
                    order_id=order_id,
                    symbol=symbol,
                    direction=order.direction,
                    order_type=order.order_type,
                    limit_price=limit_price,
                    action=ReconciliationAction.CANCEL,
                    reason=reason,
                    market_price=market_price,
                    consensus_score=cons_score,
                    timestamp=now
                ))
                continue

            # Condition 3: Institutional Risk Invariants (Configured lot size bounds, TP points 100-300)
            if order.lot_size < config.min_lot_size or order.lot_size > config.max_lot_size or abs(order.lot_size - config.fixed_lot_size) > 1e-4:
                order.status = OrderStatus.CANCELLED
                reason = f"RISK_INVARIANT_BREACH: Invalid lot size {order.lot_size} (bounds [{config.min_lot_size}, {config.max_lot_size}], configured: {config.fixed_lot_size})"
                order.decision_trace.append(f"Reconciliation Cancel: {reason}")
                del self.pending_orders[order_id]
                cancelled_count += 1
                records.append(ReconciliationRecord(
                    order_id=order_id,
                    symbol=symbol,
                    direction=order.direction,
                    order_type=order.order_type,
                    limit_price=limit_price,
                    action=ReconciliationAction.CANCEL,
                    reason=reason,
                    market_price=market_price,
                    consensus_score=cons_score,
                    timestamp=now
                ))
                continue

            if order.take_profit_points is not None and (
                order.take_profit_points < config.take_profit_points_min or order.take_profit_points > config.take_profit_points_max
            ):
                    order.status = OrderStatus.CANCELLED
                    reason = f"RISK_INVARIANT_BREACH: TP points {order.take_profit_points} outside [{config.take_profit_points_min}, {config.take_profit_points_max}]"
                    order.decision_trace.append(f"Reconciliation Cancel: {reason}")
                    del self.pending_orders[order_id]
                    cancelled_count += 1
                    records.append(ReconciliationRecord(
                        order_id=order_id,
                        symbol=symbol,
                        direction=order.direction,
                        order_type=order.order_type,
                        limit_price=limit_price,
                        action=ReconciliationAction.CANCEL,
                        reason=reason,
                        market_price=market_price,
                        consensus_score=cons_score,
                        timestamp=now
                    ))
                    continue

            # Condition 2: Swarm Consensus Reversal
            if cons:
                is_reversed = False
                if order.direction == OrderDirection.BUY and cons.direction == OrderDirection.SELL and cons.score >= config.consensus_signal_min or order.direction == OrderDirection.SELL and cons.direction == OrderDirection.BUY and cons.score >= config.consensus_signal_min:
                    is_reversed = True

                if is_reversed:
                    order.status = OrderStatus.CANCELLED
                    reason = f"SWARM_CONSENSUS_REVERSED: Swarm shifted to {cons.direction.value} ({cons.score*100:.1f}%)"
                    order.decision_trace.append(f"Reconciliation Cancel: {reason}")
                    del self.pending_orders[order_id]
                    cancelled_count += 1
                    records.append(ReconciliationRecord(
                        order_id=order_id,
                        symbol=symbol,
                        direction=order.direction,
                        order_type=order.order_type,
                        limit_price=limit_price,
                        action=ReconciliationAction.CANCEL,
                        reason=reason,
                        market_price=market_price,
                        consensus_score=cons_score,
                        timestamp=now
                    ))
                    continue

            # Condition 1: Price Validity & Gap Inversion
            if tick:
                is_inverted = False
                if (
                    order.order_type == OrderType.BUY_LIMIT and (tick.ask <= limit_price or tick.price <= limit_price)
                ) or (
                    order.order_type == OrderType.SELL_LIMIT and (tick.bid >= limit_price or tick.price >= limit_price)
                ):
                    is_inverted = True

                if is_inverted:
                    order.status = OrderStatus.CANCELLED
                    reason = f"PRICE_INVERTED_DURING_DOWNTIME: Limit {limit_price:.4f} crossed by market (bid={tick.bid:.4f}, ask={tick.ask:.4f})"
                    order.decision_trace.append(f"Reconciliation Cancel: {reason}")
                    del self.pending_orders[order_id]
                    cancelled_count += 1
                    records.append(ReconciliationRecord(
                        order_id=order_id,
                        symbol=symbol,
                        direction=order.direction,
                        order_type=order.order_type,
                        limit_price=limit_price,
                        action=ReconciliationAction.CANCEL,
                        reason=reason,
                        market_price=market_price,
                        consensus_score=cons_score,
                        timestamp=now
                    ))
                    continue

            # All checks passed: Retain order
            retained_count += 1
            order.decision_trace.append("Reconciliation: Order validated and retained")
            records.append(ReconciliationRecord(
                order_id=order_id,
                symbol=symbol,
                direction=order.direction,
                order_type=order.order_type,
                limit_price=limit_price,
                action=ReconciliationAction.RETAIN,
                reason="ORDER_VALIDATED_POST_RECONNECT",
                market_price=market_price,
                consensus_score=cons_score,
                timestamp=now
            ))

        self.portfolio.pending_orders = list(self.pending_orders.values())
        self.portfolio.open_positions = list(self.active_positions.values())

        report = ReconciliationReport(
            reconciliation_id=f"REC-{uuid.uuid4().hex[:8].upper()}",
            timestamp=now,
            downtime_seconds=downtime_seconds,
            total_reviewed=total_reviewed,
            retained_count=retained_count,
            cancelled_count=cancelled_count,
            filled_count=filled_count,
            records=records
        )
        self.portfolio.last_reconciliation = report
        self.portfolio.network_status = NetworkStatus.SYNCED
        logger.info(f"Order reconciliation complete: Reviewed={total_reviewed} Retained={retained_count} Cancelled={cancelled_count} AdoptedFilled={filled_count}")
        return report

    def apply_trailing_stop(self, tick: MarketTick) -> list[str]:
        """Ratchets trailing stop loss in profit direction, closes position if SL is touched."""
        msgs: list[str] = []
        if not config.trailing_stop_enabled:
            return msgs

        for pos_id, pos in list(self.active_positions.items()):
            if pos.symbol != tick.symbol:
                continue

            decimals = 4 if pos.symbol == "EURUSD" else 2

            if pos.direction == OrderDirection.BUY:
                if tick.price > pos.highest_price:
                    pos.highest_price = tick.price

                profit_delta = tick.price - pos.entry_price
                if profit_delta >= pos.trail_activation_delta:
                    pos.trailing_active = True
                    potential_sl = round(tick.price - pos.trail_distance, decimals)
                    if pos.stop_loss is None or potential_sl > pos.stop_loss:
                        pos.stop_loss = potential_sl
                        msgs.append(f"Trailing SL ratcheted for {pos.symbol} BUY -> {pos.stop_loss:.{decimals}f}")

                # Stop loss hit check
                if pos.stop_loss is not None and tick.bid <= pos.stop_loss:
                    realized = self.close_position(pos_id, pos.stop_loss)
                    msgs.append(f"Trailing Stop Triggered: Closed {pos.symbol} BUY @ {pos.stop_loss:.{decimals}f}: P&L ${realized:+.2f}")

            elif pos.direction == OrderDirection.SELL:
                if pos.lowest_price == 0.0 or tick.price < pos.lowest_price:
                    pos.lowest_price = tick.price

                profit_delta = pos.entry_price - tick.price
                if profit_delta >= pos.trail_activation_delta:
                    pos.trailing_active = True
                    potential_sl = round(tick.price + pos.trail_distance, decimals)
                    if pos.stop_loss is None or potential_sl < pos.stop_loss:
                        pos.stop_loss = potential_sl
                        msgs.append(f"Trailing SL ratcheted for {pos.symbol} SELL -> {pos.stop_loss:.{decimals}f}")

                # Stop loss hit check
                if pos.stop_loss is not None and tick.ask >= pos.stop_loss:
                    realized = self.close_position(pos_id, pos.stop_loss)
                    msgs.append(f"Trailing Stop Triggered: Closed {pos.symbol} SELL @ {pos.stop_loss:.{decimals}f}: P&L ${realized:+.2f}")

        self.portfolio.open_positions = list(self.active_positions.values())
        return msgs

    def apply_take_profit(self, tick: MarketTick) -> list[str]:
        """Auto-closes positions when mark price reaches the automated Take Profit target (100-300 points)."""
        msgs: list[str] = []
        if not config.take_profit_enabled:
            return msgs

        for pos_id, pos in list(self.active_positions.items()):
            if pos.symbol != tick.symbol or pos.take_profit is None:
                continue

            decimals = 5 if pos.symbol == "EURUSD" else 2
            hit = False

            if (
                pos.direction == OrderDirection.BUY and (tick.bid >= pos.take_profit or tick.price >= pos.take_profit)
            ) or (
                pos.direction == OrderDirection.SELL and (tick.ask <= pos.take_profit or tick.price <= pos.take_profit)
            ):
                hit = True

            if hit:
                realized = self.close_position(pos_id, pos.take_profit)
                pts = pos.take_profit_points or config.take_profit_points
                msg = f"Auto Take Profit Hit (+{pts} pt): Closed {pos.symbol} {pos.direction.value} @ {pos.take_profit:.{decimals}f}: P&L ${realized:+.2f}"
                msgs.append(msg)
                logger.info(msg)

        self.portfolio.open_positions = list(self.active_positions.values())
        return msgs

    def update_positions(self, tick: MarketTick) -> list[str]:
        """Updates mark-to-market valuations and auto-closes positions reaching take-profit/stop-loss."""
        closed_msgs = []
        total_unrealized = 0.0

        for pos_id, pos in list(self.active_positions.items()):
            if pos.symbol == tick.symbol:
                pos.current_price = tick.price
                diff = (tick.price - pos.entry_price) if pos.direction == OrderDirection.BUY else (pos.entry_price - tick.price)
                mult = 100.0 if pos.symbol == "XAUUSD" else (1.0 if pos.symbol == "BTCUSD" else (1000.0 if pos.symbol == "USOIL" else 100000.0))
                pos.unrealized_pnl = round(diff * pos.lot_size * mult, 2)

                # Auto take profit if gain > $500 or stop loss if loss < -$300
                if pos.unrealized_pnl >= 500.0 or pos.unrealized_pnl <= -300.0:
                    realized = self.close_position(pos_id, tick.price)
                    closed_msgs.append(f"Auto-closed {pos.symbol} {pos.direction.value}: P&L ${realized:+.2f}")

            total_unrealized += pos.unrealized_pnl

        self.portfolio.unrealized_pnl = round(total_unrealized, 2)
        self.portfolio.open_positions = list(self.active_positions.values())

        # If positions still exceed or equal capacity, rotate the oldest position
        if len(self.active_positions) >= config.max_open_positions:
            oldest_id = next(iter(self.active_positions))
            p = self.active_positions[oldest_id]
            realized = self.close_position(oldest_id, p.current_price)
            closed_msgs.append(f"Capacity rotation: Closed {p.symbol} {p.direction.value}: P&L ${realized:+.2f}")

        return closed_msgs

    def close_position(self, position_id: str, exit_price: float) -> float:
        if position_id not in self.active_positions:
            return 0.0
        pos = self.active_positions.pop(position_id)
        diff = (exit_price - pos.entry_price) if pos.direction == OrderDirection.BUY else (pos.entry_price - exit_price)
        mult = 100.0 if pos.symbol == "XAUUSD" else (1.0 if pos.symbol == "BTCUSD" else (1000.0 if pos.symbol == "USOIL" else 100000.0))
        realized = round(diff * pos.lot_size * mult, 2)
        pos.realized_pnl = realized
        self.portfolio.realized_pnl_mtd += realized
        self.portfolio.net_equity += realized
        self.portfolio.open_positions = list(self.active_positions.values())
        return realized

    def get_recent_orders(self, limit: int = 15) -> list[TradeOrder]:
        return list(self.orders.values())[-limit:]
