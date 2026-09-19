"""Tests for MT5 Take Profit synchronization engine, symbol calibration, and broker SL/TP orders."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from cyber_swarm.core.models import OrderDirection
from cyber_swarm.execution.mt5_connector import MT5Connector


def test_calculate_target_tp_buy_and_sell():
    conn = MT5Connector()
    # In disconnected simulation mode
    conn.connected = False

    # XAUUSD: 200 points = 2.00
    buy_tp = conn.calculate_target_tp("XAUUSD", OrderDirection.BUY, 2400.00, points=200)
    assert buy_tp == 2402.00

    sell_tp = conn.calculate_target_tp("XAUUSD", OrderDirection.SELL, 2400.00, points=200)
    assert sell_tp == 2398.00

    # EURUSD: 200 points = 0.00200
    eur_buy = conn.calculate_target_tp("EURUSD", OrderDirection.BUY, 1.08500, points=200)
    assert eur_buy == 1.08700

    eur_sell = conn.calculate_target_tp("EURUSD", OrderDirection.SELL, 1.08500, points=200)
    assert eur_sell == 1.08300


def test_calculate_target_tp_clamping():
    conn = MT5Connector()
    conn.connected = False

    # Below min (50 clamped to 100 pt = 1.00)
    tp_low = conn.calculate_target_tp("XAUUSD", OrderDirection.BUY, 2400.00, points=50)
    assert tp_low == 2401.00

    # Above max (500 clamped to 300 pt = 3.00)
    tp_high = conn.calculate_target_tp("XAUUSD", OrderDirection.BUY, 2400.00, points=500)
    assert tp_high == 2403.00


def test_sync_open_positions_tp_with_mock():
    conn = MT5Connector()
    conn.connected = True

    mock_pos_1 = MagicMock()
    mock_pos_1.ticket = 101
    mock_pos_1.symbol = "XAUUSD"
    mock_pos_1.type = 1  # SELL
    mock_pos_1.price_open = 2400.00
    mock_pos_1.price_current = 2400.00
    mock_pos_1.sl = 0.0
    mock_pos_1.tp = 0.0

    mock_pos_2 = MagicMock()
    mock_pos_2.ticket = 102
    mock_pos_2.symbol = "XAUUSD"
    mock_pos_2.type = 0  # BUY
    mock_pos_2.price_open = 2400.00
    mock_pos_2.price_current = 2400.00
    mock_pos_2.sl = 0.0
    mock_pos_2.tp = 2402.00  # Already has TP

    mock_mt5 = MagicMock()
    mock_mt5.positions_get.return_value = [mock_pos_1, mock_pos_2]
    mock_mt5.TRADE_ACTION_SLTP = 6
    mock_mt5.TRADE_RETCODE_DONE = 10009

    mock_res = MagicMock()
    mock_res.retcode = 10009
    mock_mt5.order_send.return_value = mock_res
    mock_mt5.symbol_info.return_value = MagicMock(point=0.01, digits=2, trade_stops_level=0)
    mock_mt5.symbol_info_tick.return_value = MagicMock(bid=2400.00, ask=2400.25)

    with patch.dict("sys.modules", {"MetaTrader5": mock_mt5}):
        count = conn.sync_open_positions_tp(points=200)
        assert count == 1
        assert mock_mt5.order_send.called
        call_args = mock_mt5.order_send.call_args[0][0]
        assert call_args["action"] == mock_mt5.TRADE_ACTION_SLTP
        assert call_args["position"] == 101
        assert call_args["tp"] == 2398.00


def test_sync_pending_orders_tp_with_mock():
    conn = MT5Connector()
    conn.connected = True

    mock_ord_1 = MagicMock()
    mock_ord_1.ticket = 201
    mock_ord_1.symbol = "XAUUSD"
    mock_ord_1.type = 2  # BUY_LIMIT
    mock_ord_1.price_open = 2390.00
    mock_ord_1.sl = 0.0
    mock_ord_1.tp = 0.0
    mock_ord_1.type_time = 0
    mock_ord_1.type_filling = 1

    mock_mt5 = MagicMock()
    mock_mt5.orders_get.return_value = [mock_ord_1]
    mock_mt5.ORDER_TYPE_BUY_LIMIT = 2
    mock_mt5.TRADE_ACTION_MODIFY = 7
    mock_mt5.TRADE_RETCODE_DONE = 10009

    mock_res = MagicMock()
    mock_res.retcode = 10009
    mock_mt5.order_send.return_value = mock_res
    mock_mt5.symbol_info.return_value = MagicMock(point=0.01, digits=2, trade_stops_level=0)
    mock_mt5.symbol_info_tick.return_value = None

    with patch.dict("sys.modules", {"MetaTrader5": mock_mt5}):
        count = conn.sync_pending_orders_tp(points=200)
        assert count == 1
        assert mock_mt5.order_send.called
        call_args = mock_mt5.order_send.call_args[0][0]
        assert call_args["action"] == mock_mt5.TRADE_ACTION_MODIFY
        assert call_args["order"] == 201
        assert call_args["tp"] == 2392.00


def test_send_pending_limit_order_auto_includes_tp():
    conn = MT5Connector()
    conn.connected = True

    mock_mt5 = MagicMock()
    mock_mt5.ORDER_TYPE_BUY_LIMIT = 2
    mock_mt5.TRADE_ACTION_PENDING = 5
    mock_mt5.ORDER_TIME_GTC = 0
    mock_mt5.ORDER_FILLING_IOC = 1
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_res = MagicMock(retcode=10009, order=999)
    mock_mt5.order_send.return_value = mock_res
    mock_mt5.symbol_info.return_value = MagicMock(point=0.01, digits=2, trade_stops_level=0)
    mock_mt5.symbol_info_tick.return_value = None

    with patch.dict("sys.modules", {"MetaTrader5": mock_mt5}):
        # Call without explicit tp -> auto TP should be calculated and sent
        order_ticket = conn.send_pending_limit_order("XAUUSD", OrderDirection.BUY, 2390.00, lot_size=0.10)
        assert order_ticket == 999
        sent_request = mock_mt5.order_send.call_args[0][0]
        assert "tp" in sent_request
        assert sent_request["tp"] == 2392.00


def test_api_sync_tp_endpoint():
    from cyber_swarm.server.app import app
    client = TestClient(app)

    response = client.post("/api/mt5/sync-tp")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "open_positions_synced" in data
    assert "pending_orders_synced" in data
