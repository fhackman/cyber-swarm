"""Tests for AICL Protocol Engine"""
from cyber_swarm.core.aicl import AICLMessage

def test_aicl_encode_decode():
    raw_msg = "@SET TIDAL>ORC|CTX=TRD+SMC|OBJ=SIG|CON=RISK<=0.02|DATA=sym:XAUUSD,dir:SELL,cf:0.92|OUT=VOTE|ST=RDY"
    decoded = AICLMessage.decode(raw_msg)

    assert decoded.action == "SET"
    assert decoded.source == "TIDAL"
    assert decoded.destination == "ORC"
    assert decoded.context == "TRD+SMC"
    assert decoded.data["sym"] == "XAUUSD"
    assert decoded.data["dir"] == "SELL"
    assert decoded.data["cf"] == 0.92
    assert decoded.state == "RDY"

    # Test roundtrip encoding
    encoded = decoded.encode()
    assert "@SET TIDAL>ORC" in encoded
    assert "CTX=TRD+SMC" in encoded
    assert "DATA=sym:XAUUSD,dir:SELL,cf:0.92" in encoded

def test_aicl_delta_update():
    msg = AICLMessage(
        action="ANL",
        source="ZEPHR",
        destination="ORC",
        data={"spread": 1.2, "vol": 100}
    )
    # Apply delta
    msg.apply_delta("Δ:+skew=3.2;~spread=0.8;-vol")

    assert msg.data["skew"] == "3.2"
    assert msg.data["spread"] == "0.8"
    assert "vol" not in msg.data
