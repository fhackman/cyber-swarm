"""Unit Tests for Quant & SMC Feature Engine"""
import pytest
from datetime import datetime, timezone
from cyber_swarm.quant.features import QuantFeatureEngine, Candle, MarketStructure

def test_atr_calculation():
    engine = QuantFeatureEngine()
    candles = [
        Candle(open=100.0, high=105.0, low=95.0, close=102.0),
        Candle(open=102.0, high=108.0, low=101.0, close=106.0),
        Candle(open=106.0, high=110.0, low=104.0, close=105.0),
    ]
    atr = engine.calculate_atr(candles, period=2)
    assert atr > 0.0
    assert isinstance(atr, float)

def test_fvg_detection_bullish():
    engine = QuantFeatureEngine()
    # Candle 1: High at 100.0
    # Candle 2: Strong expansion candle (101.0 to 112.0)
    # Candle 3: Low at 104.0 -> Gap between c3.low (104.0) and c1.high (100.0) is 4.0 (Bullish Discount FVG)
    candles = [
        Candle(open=95.0, high=100.0, low=94.0, close=99.0),
        Candle(open=100.0, high=112.0, low=100.0, close=110.0),
        Candle(open=110.0, high=115.0, low=104.0, close=112.0),
    ]
    fvgs = engine.detect_fvg(candles)
    assert len(fvgs) >= 1
    assert fvgs[0]["type"] == "BULLISH_DISCOUNT"
    assert fvgs[0]["bottom"] == 100.0
    assert fvgs[0]["top"] == 104.0
    assert fvgs[0]["gap_size"] == 4.0

def test_swings_and_bos_structure():
    engine = QuantFeatureEngine()
    candles = [
        Candle(open=100.0, high=102.0, low=98.0, close=101.0),
        Candle(open=101.0, high=105.0, low=100.0, close=104.0),
        Candle(open=104.0, high=110.0, low=103.0, close=109.0), # Swing high
        Candle(open=109.0, high=107.0, low=102.0, close=103.0),
        Candle(open=103.0, high=104.0, low=99.0, close=100.0),  # Swing low
        Candle(open=100.0, high=108.0, low=100.0, close=107.0),
        Candle(open=107.0, high=115.0, low=106.0, close=114.0)  # Breaks 110.0 -> BOS Bullish
    ]
    swings = engine.detect_swings(candles, lookback=1)
    assert 110.0 in swings["highs"]
    structure = engine.detect_market_structure(candles, swings)
    assert structure == MarketStructure.BOS_BULLISH

def test_feature_snapshot_generation():
    engine = QuantFeatureEngine()
    candles = [
        Candle(open=2380.0, high=2385.0, low=2378.0, close=2382.0)
        for _ in range(25)
    ]
    engine.load_candles("XAUUSD", "M15", candles)
    snap = engine.calculate_features("XAUUSD", "M15")
    assert snap.symbol == "XAUUSD"
    assert snap.timeframe == "M15"
    assert snap.current_price == 2382.0
    assert snap.atr > 0.0
    assert snap.ema_20 > 0.0
