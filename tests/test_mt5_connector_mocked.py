"""Comprehensive Mock Unit Tests for MetaTrader 5 Bridge Connector (MT5Connector)"""
import sys
from unittest.mock import MagicMock, patch

from cyber_swarm.core.models import OrderDirection, NetworkStatus
from cyber_swarm.execution.mt5_connector import MT5Connector


def test_mt5_connector_init_disconnected():
    with patch("builtins.__import__", side_effect=ImportError("No module named 'MetaTrader5'")):
        conn = MT5Connector()
        assert conn.connected is False
        assert conn.network_status == NetworkStatus.DISCONNECTED
        info = conn.get_real_account_info()
        assert info["connected"] is False


def test_mt5_connector_init_success():
    mock_mt5 = MagicMock()
    mock_mt5.initialize.return_value = True
    mock_term = MagicMock(ping_last=5000, connected=True)
    mock_acc = MagicMock(login=998877, name="Test User", server="Eightcap-Demo", equity=50000.0, balance=50000.0)
    mock_mt5.terminal_info.return_value = mock_term
    mock_mt5.account_info.return_value = mock_acc
    mock_mt5.symbol_info.return_value = MagicMock(visible=True)

    with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
        conn = MT5Connector()
        assert conn.connected is True
        assert conn.account_id == "998877"
        assert conn.equity == 50000.0
        assert conn.ping_ms == 5.0
        info = conn.get_real_account_info()
        assert info["connected"] is True
        assert info["login"] == "998877"


def test_check_live_connection_transitions():
    mock_mt5 = MagicMock()
    mock_mt5.initialize.return_value = True
    mock_mt5.terminal_info.return_value = MagicMock(connected=True, ping_last=4200)

    with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
        conn = MT5Connector()
        conn.connected = True

        # Simulate disconnect
        mock_mt5.terminal_info.return_value = MagicMock(connected=False)
        mock_mt5.initialize.return_value = False
        res = conn.check_live_connection()
        assert res is False
        assert conn.connected is False
        assert conn.network_status == NetworkStatus.DISCONNECTED
        assert conn.disconnected_at is not None

        # Simulate reconnect
        mock_mt5.terminal_info.return_value = MagicMock(connected=True, ping_last=3000)
        res2 = conn.check_live_connection()
        assert res2 is True
        assert conn.connected is True
        assert conn.reconnected_event is True
        assert conn.network_status == NetworkStatus.RECONCILING


def test_fetch_live_positions_mocked():
    mock_mt5 = MagicMock()
    mock_mt5.initialize.return_value = True
    raw_pos = MagicMock(
        ticket=123456,
        symbol="XAUUSD",
        type=0,  # BUY
        volume=0.2,
        price_open=2700.0,
        price_current=2710.0,
        sl=2690.0,
        tp=2720.0,
        profit=200.0,
        time=1700000000
    )
    mock_mt5.positions_get.return_value = [raw_pos]
    mock_mt5.symbol_info.return_value = MagicMock(point=0.01, visible=True)

    with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
        conn = MT5Connector()
        conn.connected = True
        positions = conn.fetch_live_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.position_id == "TICKET-123456"
        assert pos.direction == OrderDirection.BUY
        assert pos.lot_size == 0.2
        assert pos.entry_price == 2700.0
        assert pos.unrealized_pnl == 200.0


def test_modify_position_sltp_success_and_fail():
    mock_mt5 = MagicMock()
    mock_mt5.initialize.return_value = True
    mock_mt5.TRADE_ACTION_SLTP = 1
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.order_send.return_value = MagicMock(retcode=10009)

    with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
        conn = MT5Connector()
        conn.connected = True
        # Success
        assert conn.modify_position_sltp(123456, sl=2700.0, tp=2750.0, symbol="XAUUSD") is True

        # Failure
        mock_mt5.order_send.return_value = MagicMock(retcode=10013, comment="Invalid request")
        assert conn.modify_position_sltp(123456, sl=2700.0, tp=2750.0, symbol="XAUUSD") is False

        # Disconnected
        conn.connected = False
        assert conn.modify_position_sltp(123456, sl=2700.0, tp=2750.0) is False


def test_sync_open_and_pending_orders_tp_mocked():
    mock_mt5 = MagicMock()
    mock_mt5.initialize.return_value = True
    mock_mt5.TRADE_ACTION_MODIFY = 2
    mock_mt5.TRADE_ACTION_SLTP = 1
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.ORDER_TYPE_BUY_LIMIT = 2
    mock_mt5.order_send.return_value = MagicMock(retcode=10009)
    mock_mt5.symbol_info.return_value = MagicMock(point=0.01, digits=2, trade_stops_level=0, visible=True)
    mock_mt5.symbol_info_tick.return_value = MagicMock(bid=2700.0, ask=2700.25)

    raw_pos = MagicMock(ticket=101, symbol="XAUUSD", type=0, price_open=2700.0, sl=0.0, tp=0.0)
    mock_mt5.positions_get.return_value = [raw_pos]

    raw_order = MagicMock(
        ticket=202,
        symbol="XAUUSD",
        type=2,
        price_open=2690.0,
        sl=0.0,
        tp=0.0,
        type_time=1,
        type_filling=1
    )
    mock_mt5.orders_get.return_value = [raw_order]

    with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
        conn = MT5Connector()
        conn.connected = True
        synced_pos = conn.sync_open_positions_tp(points=200)
        assert synced_pos == 1

        synced_orders = conn.sync_pending_orders_tp(points=200)
        assert synced_orders == 1


def test_send_pending_limit_order_success_and_fail():
    mock_mt5 = MagicMock()
    mock_mt5.initialize.return_value = True
    mock_mt5.ORDER_TYPE_BUY_LIMIT = 2
    mock_mt5.ORDER_TIME_GTC = 1
    mock_mt5.ORDER_FILLING_IOC = 1
    mock_mt5.TRADE_ACTION_PENDING = 5
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.order_send.return_value = MagicMock(retcode=10009, order=998822)

    with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
        conn = MT5Connector()
        conn.connected = True
        order_ticket = conn.send_pending_limit_order("XAUUSD", OrderDirection.BUY, 2700.0, lot_size=0.1, tp=2710.0)
        assert order_ticket == 998822

        # Failure
        mock_mt5.order_send.return_value = MagicMock(retcode=10013, comment="Market closed")
        assert conn.send_pending_limit_order("XAUUSD", OrderDirection.BUY, 2700.0) is None


def test_fetch_tick_with_symbol_info_tick():
    mock_mt5 = MagicMock()
    mock_mt5.initialize.return_value = True
    mock_mt5.TIMEFRAME_D1 = 16408
    mock_tick = MagicMock(
        bid=2740.10,
        ask=2740.35,
        last=2740.20,
        volume_real=1500.0,
        volume=100.0,
        time_msc=1700000000123
    )
    mock_mt5.symbol_info_tick.return_value = mock_tick
    mock_mt5.copy_rates_from_pos.return_value = [(1700000000, 2735.0, 2745.0, 2730.0, 2740.0, 100, 20, 100)]

    with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
        conn = MT5Connector()
        conn.connected = True
        conn.resolved_symbols["XAUUSD"] = "XAUUSD"

        import asyncio
        tick = asyncio.run(conn.fetch_tick("XAUUSD"))
        assert tick.symbol == "XAUUSD"
        assert tick.price == 2740.225
        assert tick.bid == 2740.10
        assert tick.ask == 2740.35
        assert round(tick.spread, 2) == 0.25
        assert tick.change_pct > 0
