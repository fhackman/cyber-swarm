"""CYBER SWARM TRADING OS - MetaTrader 5 Bridge Connector

Direct institutional connection to live MetaTrader 5 terminal:
- Real-time tick stream and spread analysis
- Daily change % calculated from D1 bar open
- Account equity, balance, leverage, and ping synchronization
- Live position reconciliation directly from broker account
"""
import os
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import logging

from cyber_swarm.core.models import (
    MarketTick,
    Position,
    OrderDirection,
    PortfolioState,
    TradeOrder,
    OrderStatus,
    OrderType,
    NetworkStatus
)
from cyber_swarm.core.config import config

logger = logging.getLogger("cyber_swarm.mt5")

SYMBOL_CANDIDATES = {
    "XAUUSD": ["XAUUSD", "GOLD", "XAUUSDm", "XAUUSD.c"],
    "BTCUSD": ["BTCUSD", "WBTCUSD", "BTCUSD.c", "BITCOIN"],
    "EURUSD": ["EURUSD", "EURUSD.i", "EURUSDm", "EURUSD.c"],
    "USOIL": ["USOUSD", "USO", "WTICRUDE", "XTIUSD", "USOIL"]
}

class MT5Connector:
    def __init__(self):
        self.connected: bool = False
        self.ping_ms: float = 4.2
        self.account_id: str = "QUANT-DESK-01"
        self.account_name: str = "Demo Desk"
        self.server_name: str = "Internal"
        self.equity: float = config.initial_equity
        self.balance: float = config.initial_equity
        self.resolved_symbols: Dict[str, str] = {}
        self.network_status: NetworkStatus = NetworkStatus.ONLINE
        self.disconnected_at: Optional[datetime] = None
        self.downtime_duration_seconds: float = 0.0
        self.reconnected_event: bool = False
        self._check_connection()
        self.network_status = NetworkStatus.ONLINE if self.connected else NetworkStatus.DISCONNECTED

    def _check_connection(self):
        try:
            import MetaTrader5 as mt5
            if mt5.initialize():
                self.connected = True
                term = mt5.terminal_info()
                acc = mt5.account_info()
                if acc:
                    self.account_id = str(acc.login)
                    self.account_name = acc.name
                    self.server_name = acc.server
                    self.equity = float(acc.equity)
                    self.balance = float(acc.balance)
                if term:
                    self.ping_ms = round(term.ping_last / 1000.0, 1) if term.ping_last else 4.2

                self._resolve_symbols(mt5)
                logger.info(f"MetaTrader 5 Connected: Account={self.account_id} ({self.account_name}) Server={self.server_name} Equity=${self.equity:,.2f} Ping={self.ping_ms}ms")
            else:
                self.connected = False
                logger.warning("MetaTrader 5 initialization failed. Falling back to Paper Simulation Feed.")
        except Exception as e:
            self.connected = False
            logger.warning(f"MetaTrader 5 library exception ({e}). Falling back to Paper Simulation Feed.")

    def check_live_connection(self) -> bool:
        """Polls MT5 terminal for live socket/network connection and detects reconnection events."""
        was_connected = self.connected
        is_currently_connected = False
        try:
            import MetaTrader5 as mt5
            term = mt5.terminal_info()
            if term and getattr(term, "connected", False):
                is_currently_connected = True
                if term.ping_last:
                    self.ping_ms = round(term.ping_last / 1000.0, 1)
            elif term and not hasattr(term, "connected"):
                is_currently_connected = True
            else:
                if mt5.initialize():
                    is_currently_connected = True
        except Exception as e:
            is_currently_connected = False

        if was_connected and not is_currently_connected:
            self.connected = False
            self.network_status = NetworkStatus.DISCONNECTED
            self.disconnected_at = datetime.now(timezone.utc)
            logger.warning("MetaTrader 5 network disconnect detected! Transitioning to DISCONNECTED.")
        elif not was_connected and is_currently_connected:
            self.connected = True
            if self.disconnected_at:
                self.downtime_duration_seconds = round((datetime.now(timezone.utc) - self.disconnected_at).total_seconds(), 2)
            else:
                self.downtime_duration_seconds = 0.0
            self.network_status = NetworkStatus.RECONCILING
            self.reconnected_event = True
            self.disconnected_at = None
            logger.info(f"MetaTrader 5 connection restored after {self.downtime_duration_seconds}s! Transitioning to RECONCILING state.")
        elif is_currently_connected:
            if self.network_status != NetworkStatus.RECONCILING:
                self.network_status = NetworkStatus.ONLINE
        else:
            self.network_status = NetworkStatus.DISCONNECTED
            if self.disconnected_at:
                self.downtime_duration_seconds = round((datetime.now(timezone.utc) - self.disconnected_at).total_seconds(), 2)

        return self.connected

    def simulate_network_disconnect(self):
        """Simulates network disconnection for testing & validation."""
        self.connected = False
        self.network_status = NetworkStatus.DISCONNECTED
        self.disconnected_at = datetime.now(timezone.utc)
        logger.warning("Simulated network disconnect triggered.")

    def simulate_network_reconnect(self, downtime_seconds: float = 5.0):
        """Simulates network restoration for testing & validation."""
        self.connected = True
        self.network_status = NetworkStatus.RECONCILING
        self.downtime_duration_seconds = downtime_seconds
        self.reconnected_event = True
        self.disconnected_at = None
        logger.info(f"Simulated network reconnection triggered (downtime: {downtime_seconds}s).")

    def _resolve_symbols(self, mt5):
        """Discovers actual broker symbol names from available candidate list."""
        available_symbols = {s.name for s in mt5.symbols_get() or []}
        for standard_sym, candidates in SYMBOL_CANDIDATES.items():
            for c in candidates:
                if c in available_symbols:
                    self.resolved_symbols[standard_sym] = c
                    mt5.symbol_select(c, True)
                    break
            if standard_sym not in self.resolved_symbols:
                self.resolved_symbols[standard_sym] = standard_sym

    def get_real_account_info(self) -> Dict[str, Any]:
        """Returns verified real account metrics from MT5."""
        if not self.connected:
            return {
                "connected": False,
                "login": "SIMULATED",
                "name": "Quant Desk Sim",
                "server": "Simulation",
                "equity": config.initial_equity,
                "balance": config.initial_equity,
                "ping_ms": 4.2,
                "network_status": self.network_status.value,
                "downtime_seconds": self.downtime_duration_seconds
            }
        try:
            import MetaTrader5 as mt5
            acc = mt5.account_info()
            term = mt5.terminal_info()
            if acc:
                self.equity = float(acc.equity)
                self.balance = float(acc.balance)
            if term and term.ping_last:
                self.ping_ms = round(term.ping_last / 1000.0, 1)
            return {
                "connected": True,
                "login": str(acc.login) if acc else self.account_id,
                "name": acc.name if acc else self.account_name,
                "server": acc.server if acc else self.server_name,
                "equity": self.equity,
                "balance": self.balance,
                "leverage": acc.leverage if acc else 500,
                "ping_ms": self.ping_ms,
                "network_status": self.network_status.value,
                "downtime_seconds": self.downtime_duration_seconds
            }
        except Exception as e:
            logger.error(f"Error fetching MT5 account info: {e}")
            return {
                "connected": False,
                "equity": self.equity,
                "balance": self.balance,
                "ping_ms": self.ping_ms,
                "network_status": self.network_status.value,
                "downtime_seconds": self.downtime_duration_seconds
            }

    async def fetch_tick(self, symbol: str) -> MarketTick:
        """Fetches the latest real tick from MT5 if connected, else fallback to high-fidelity feed."""
        actual_symbol = self.resolved_symbols.get(symbol, symbol)
        
        if self.connected:
            try:
                import MetaTrader5 as mt5
                tick_data = mt5.symbol_info_tick(actual_symbol)
                if tick_data and tick_data.bid > 0 and tick_data.ask > 0:
                    mid = round((tick_data.bid + tick_data.ask) / 2.0, 5)
                    spread = round(tick_data.ask - tick_data.bid, 5)
                    
                    # Calculate real 24h change % from D1 bar open
                    change_pct = 0.0
                    rates = mt5.copy_rates_from_pos(actual_symbol, mt5.TIMEFRAME_D1, 0, 1)
                    if rates is not None and len(rates) > 0:
                        daily_open = rates[0][1]
                        if daily_open > 0:
                            change_pct = round(((mid - daily_open) / daily_open) * 100.0, 2)
                    
                    return MarketTick(
                        symbol=symbol,  # Normalized standard symbol for Swarm
                        price=mid,
                        bid=tick_data.bid,
                        ask=tick_data.ask,
                        spread=spread,
                        volume_24h=float(tick_data.volume if tick_data.volume else 150000.0),
                        change_pct=change_pct
                    )
            except Exception as e:
                logger.error(f"MT5 tick retrieval error for {actual_symbol}: {e}")

        # Fallback simulation prices
        prices = {
            "XAUUSD": 2384.42,
            "BTCUSD": 67412.10,
            "EURUSD": 1.0894,
            "USOIL": 81.24
        }
        changes = {
            "XAUUSD": 0.84,
            "BTCUSD": -1.12,
            "EURUSD": 0.15,
            "USOIL": 2.10
        }
        price = prices.get(symbol, 100.0)
        spread = 0.25 if symbol == "XAUUSD" else (0.00015 if symbol == "EURUSD" else 1.0)
        return MarketTick(
            symbol=symbol,
            price=price,
            bid=price - (spread / 2.0),
            ask=price + (spread / 2.0),
            spread=spread,
            volume_24h=28400000.0,
            change_pct=changes.get(symbol, 0.5)
        )

    def calculate_target_tp(
        self,
        symbol: str,
        direction: OrderDirection,
        entry_price: float,
        points: Optional[int] = None,
        respect_current_price: bool = False
    ) -> float:
        """Calculates Take Profit target using live MT5 symbol specification (or config fallback).
        If respect_current_price is True, adjusts TP so that MT5 will not reject with Invalid Stops (10016)
        when market price has already crossed the theoretical target.
        """
        tp_pts = points if points is not None else config.take_profit_points
        tp_pts = max(config.take_profit_points_min, min(config.take_profit_points_max, tp_pts))
        actual_symbol = self.resolved_symbols.get(symbol, symbol)

        point = config.point_sizes.get(symbol, config.point_sizes.get(actual_symbol, 0.01))
        decimals = 5 if "EUR" in symbol else (3 if "OIL" in symbol or "USO" in symbol else 2)
        stops_level = 0
        tick_bid = None
        tick_ask = None

        if self.connected:
            try:
                import MetaTrader5 as mt5
                s_info = mt5.symbol_info(actual_symbol)
                if s_info:
                    point = s_info.point
                    decimals = s_info.digits
                    stops_level = s_info.trade_stops_level or 0
                s_tick = mt5.symbol_info_tick(actual_symbol)
                if s_tick:
                    tick_bid = s_tick.bid
                    tick_ask = s_tick.ask
            except Exception as e:
                logger.warning(f"Failed to query symbol_info for {actual_symbol}: {e}")

        delta = tp_pts * point
        buffer = max(stops_level * point, delta)

        if direction == OrderDirection.BUY:
            raw_tp = entry_price + delta
            if respect_current_price and tick_bid is not None and tick_bid > 0:
                if raw_tp <= tick_bid + buffer:
                    raw_tp = tick_bid + delta
            return round(raw_tp, decimals)
        else:
            raw_tp = entry_price - delta
            if respect_current_price and tick_ask is not None and tick_ask > 0:
                if raw_tp >= tick_ask - buffer:
                    raw_tp = tick_ask - delta
            return round(raw_tp, decimals)

    def fetch_live_positions(self) -> List[Position]:
        """Fetches real open positions from MetaTrader 5 terminal, populating live TP and syncing if missing."""
        if not self.connected:
            return []
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get()
            if not positions:
                return []
            
            live_pos = []
            for p in positions:
                side = OrderDirection.BUY if p.type == 0 else OrderDirection.SELL
                actual_tp = p.tp if p.tp > 0 else None
                tp_points = None

                # If position in MT5 has no TP, automatically calculate and modify broker-side TP
                if (actual_tp is None or actual_tp == 0.0) and config.take_profit_enabled:
                    target_tp = self.calculate_target_tp(p.symbol, side, p.price_open, config.take_profit_points, respect_current_price=True)
                    if self.modify_position_sltp(p.ticket, p.sl, target_tp, p.symbol):
                        actual_tp = target_tp
                        tp_points = config.take_profit_points
                elif actual_tp is not None:
                    # Calculate point distance
                    s_info = mt5.symbol_info(p.symbol)
                    pt = s_info.point if s_info else config.point_sizes.get(p.symbol, 0.01)
                    if pt > 0:
                        tp_points = int(round(abs(actual_tp - p.price_open) / pt))

                live_pos.append(Position(
                    position_id=f"TICKET-{p.ticket}",
                    symbol=p.symbol,
                    direction=side,
                    lot_size=p.volume,
                    entry_price=p.price_open,
                    current_price=p.price_current,
                    stop_loss=p.sl if p.sl > 0 else None,
                    take_profit=actual_tp,
                    take_profit_points=tp_points,
                    unrealized_pnl=round(p.profit, 2)
                ))
            return live_pos
        except Exception as e:
            logger.error(f"Error fetching MT5 positions: {e}")
            return []

    def send_pending_limit_order(
        self,
        symbol: str,
        direction: OrderDirection,
        limit_price: float,
        lot_size: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None
    ) -> Optional[int]:
        """Sends a real pending limit order to MT5 terminal with auto Take Profit and volume normalization."""
        if not self.connected:
            return None
        try:
            import MetaTrader5 as mt5
            actual_symbol = self.resolved_symbols.get(symbol, symbol)
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == OrderDirection.BUY else mt5.ORDER_TYPE_SELL_LIMIT

            # Normalize lot size against broker symbol volume constraints
            target_lot = lot_size if lot_size is not None else config.fixed_lot_size
            s_info = mt5.symbol_info(actual_symbol)
            if s_info and hasattr(s_info, "volume_min") and isinstance(getattr(s_info, "volume_min"), (int, float)) and s_info.volume_min > 0:
                vmin = s_info.volume_min
                vmax = s_info.volume_max if (hasattr(s_info, "volume_max") and isinstance(getattr(s_info, "volume_max"), (int, float)) and s_info.volume_max > 0) else config.max_lot_size
                vstep = s_info.volume_step if (hasattr(s_info, "volume_step") and isinstance(getattr(s_info, "volume_step"), (int, float)) and s_info.volume_step > 0) else config.lot_step
                target_lot = max(vmin, min(vmax, target_lot))
                target_lot = round(round(target_lot / vstep) * vstep, 2)
            else:
                target_lot = max(config.min_lot_size, min(config.max_lot_size, round(target_lot, 2)))

            # If TP is not provided and auto TP is enabled, calculate target TP
            target_tp = tp
            if (target_tp is None or target_tp == 0.0) and config.take_profit_enabled:
                target_tp = self.calculate_target_tp(actual_symbol, direction, limit_price, config.take_profit_points)

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": actual_symbol,
                "volume": float(target_lot),
                "type": order_type,
                "price": float(limit_price),
                "deviation": 20,
                "magic": 84209,
                "comment": "CyberSwarm Auto Limit",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            if sl:
                request["sl"] = float(sl)
            if target_tp:
                request["tp"] = float(target_tp)

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"MT5 Pending Limit Order placed: ticket={result.order} {actual_symbol} @ {limit_price} (TP={target_tp})")
                return result.order
            else:
                err = result.comment if result else "Unknown MT5 error"
                logger.warning(f"Failed to place MT5 limit order for {actual_symbol}: {err}")
                return None
        except Exception as e:
            logger.error(f"Error sending MT5 pending limit order: {e}")
            return None

    def modify_position_sltp(self, ticket: int, sl: float, tp: Optional[float] = 0.0, symbol: Optional[str] = None) -> bool:
        """Modifies Stop Loss and Take Profit for an active open MT5 position."""
        if not self.connected:
            return False
        try:
            import MetaTrader5 as mt5
            actual_symbol = symbol
            if not actual_symbol:
                positions = mt5.positions_get(ticket=ticket)
                if positions:
                    actual_symbol = positions[0].symbol

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl": float(sl),
                "tp": float(tp) if tp else 0.0
            }
            if actual_symbol:
                request["symbol"] = actual_symbol

            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"MT5 Position #{ticket} ({actual_symbol}) updated: SL={sl}, TP={tp}")
                return True
            else:
                err = res.comment if res else "Unknown MT5 error"
                logger.warning(f"Failed to modify SL/TP for MT5 ticket {ticket}: {err} (code={res.retcode if res else 'None'})")
                return False
        except Exception as e:
            logger.error(f"Error modifying SL/TP for ticket {ticket}: {e}")
            return False

    def sync_open_positions_tp(self, points: Optional[int] = None) -> int:
        """Inspects all live MT5 open positions and updates any with tp == 0.0 directly on broker."""
        if not self.connected:
            return 0
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get()
            if not positions:
                return 0
            
            modified_count = 0
            for p in positions:
                if p.tp == 0.0 or p.tp is None:
                    side = OrderDirection.BUY if p.type == 0 else OrderDirection.SELL
                    target_tp = self.calculate_target_tp(p.symbol, side, p.price_open, points, respect_current_price=True)
                    success = self.modify_position_sltp(p.ticket, p.sl, target_tp, p.symbol)
                    if success:
                        modified_count += 1
                        logger.info(f"Auto-synced broker TP on open position #{p.ticket} {p.symbol} -> {target_tp}")
            return modified_count
        except Exception as e:
            logger.error(f"Error syncing open positions TP: {e}")
            return 0

    def sync_pending_orders_tp(self, points: Optional[int] = None) -> int:
        """Inspects all live MT5 pending orders and modifies any with tp == 0.0 to have proper TP."""
        if not self.connected:
            return 0
        try:
            import MetaTrader5 as mt5
            orders = mt5.orders_get()
            if not orders:
                return 0
            
            modified_count = 0
            for o in orders:
                if o.tp == 0.0 or o.tp is None:
                    side = OrderDirection.BUY if o.type in [mt5.ORDER_TYPE_BUY_LIMIT, getattr(mt5, "ORDER_TYPE_BUY_STOP", 4)] else OrderDirection.SELL
                    target_tp = self.calculate_target_tp(o.symbol, side, o.price_open, points)
                    request = {
                        "action": mt5.TRADE_ACTION_MODIFY,
                        "order": o.ticket,
                        "price": float(o.price_open),
                        "sl": float(o.sl),
                        "tp": float(target_tp),
                        "type_time": o.type_time,
                        "type_filling": o.type_filling
                    }
                    res = mt5.order_send(request)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        modified_count += 1
                        logger.info(f"Auto-synced broker TP on pending order #{o.ticket} {o.symbol} -> {target_tp}")
                    else:
                        err = res.comment if res else "Unknown"
                        logger.warning(f"Failed to modify TP on pending order #{o.ticket}: {err}")
            return modified_count
        except Exception as e:
            logger.error(f"Error syncing pending orders TP: {e}")
            return 0

    def cancel_pending_order(self, ticket: int) -> bool:
        """Cancels an active pending order on MT5."""
        if not self.connected:
            return False
        try:
            import MetaTrader5 as mt5
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket
            }
            res = mt5.order_send(request)
            return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logger.error(f"Error cancelling MT5 order {ticket}: {e}")
            return False

    def fetch_live_pending_orders(self) -> List[TradeOrder]:
        """Fetches real pending orders from MetaTrader 5 terminal."""
        if not self.connected:
            return []
        try:
            import MetaTrader5 as mt5
            orders = mt5.orders_get()
            if not orders:
                return []
            live_orders = []
            for o in orders:
                direction = OrderDirection.BUY if o.type in [mt5.ORDER_TYPE_BUY_LIMIT, getattr(mt5, "ORDER_TYPE_BUY_STOP", 4)] else OrderDirection.SELL
                order_type = OrderType.BUY_LIMIT if o.type == mt5.ORDER_TYPE_BUY_LIMIT else OrderType.SELL_LIMIT
                live_orders.append(TradeOrder(
                    order_id=f"TICKET-{o.ticket}",
                    cycle_id=84209,
                    symbol=o.symbol,
                    direction=direction,
                    order_type=order_type,
                    lot_size=o.volume_initial,
                    target_price=o.price_open,
                    stop_loss=o.sl if o.sl else None,
                    take_profit=o.tp if o.tp else None,
                    status=OrderStatus.PENDING,
                    decision_trace=[f"Live MT5 Pending Order ticket #{o.ticket}"]
                ))
            return live_orders
        except Exception as e:
            logger.error(f"Error fetching MT5 pending orders: {e}")
            return []
