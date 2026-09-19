"""Unit Tests for CYBER SWARM TRADING OS - Async Event Bus"""
import asyncio
import pytest
from cyber_swarm.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_event_bus_sync_and_async_subscription():
    bus = EventBus()
    received_sync = []
    received_async = []

    def sync_handler(payload):
        received_sync.append(payload)

    async def async_handler(payload):
        await asyncio.sleep(0.01)
        received_async.append(payload)

    await bus.subscribe("ORDER_EVENT", sync_handler)
    await bus.subscribe("ORDER_EVENT", async_handler)

    assert bus.get_subscriber_count("ORDER_EVENT") == 2
    assert bus.get_subscriber_count() == 2

    # Publish message
    await bus.publish("ORDER_EVENT", {"order_id": "ORD-001", "status": "FILLED"})
    # Allow background task to complete
    await asyncio.sleep(0.05)

    assert len(received_sync) == 1
    assert received_sync[0]["order_id"] == "ORD-001"
    assert len(received_async) == 1
    assert received_async[0]["order_id"] == "ORD-001"


@pytest.mark.asyncio
async def test_event_bus_wildcard_subscription():
    bus = EventBus()
    wildcard_events = []
    specific_events = []

    def wildcard_handler(payload):
        wildcard_events.append(payload)

    def specific_handler(payload):
        specific_events.append(payload)

    await bus.subscribe("*", wildcard_handler)
    await bus.subscribe("TICKS", specific_handler)

    await bus.publish("TICKS", {"sym": "XAUUSD", "price": 2400.50})
    await bus.publish("AUDIT", {"action": "GENESIS"})

    assert len(specific_events) == 1
    assert specific_events[0]["sym"] == "XAUUSD"
    # Wildcard receives both
    assert len(wildcard_events) == 2


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    bus = EventBus()
    events = []

    def handler(payload):
        events.append(payload)

    await bus.subscribe("NEWS", handler)
    assert bus.get_subscriber_count("NEWS") == 1

    await bus.publish("NEWS", {"headline": "Rate cut announced"})
    assert len(events) == 1

    await bus.unsubscribe("NEWS", handler)
    assert bus.get_subscriber_count("NEWS") == 0

    await bus.publish("NEWS", {"headline": "Unemployment drops"})
    assert len(events) == 1  # No additional events received


@pytest.mark.asyncio
async def test_event_bus_handler_exception_isolation():
    bus = EventBus()
    valid_events = []

    def faulty_handler(payload):
        raise ValueError("Simulated handler crash")

    def safe_handler(payload):
        valid_events.append(payload)

    await bus.subscribe("CRITICAL", faulty_handler)
    await bus.subscribe("CRITICAL", safe_handler)

    # Publish should not crash despite faulty_handler raising ValueError
    await bus.publish("CRITICAL", {"level": "ALERT"})

    assert len(valid_events) == 1
    assert valid_events[0]["level"] == "ALERT"
