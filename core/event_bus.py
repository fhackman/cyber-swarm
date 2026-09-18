"""CYBER SWARM TRADING OS - Async Event Bus"""
import asyncio
from typing import Callable, Dict, List, Any
import logging

logger = logging.getLogger("cyber_swarm.event_bus")

class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], Any]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str, handler: Callable[[Any], Any]):
        async with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            if handler not in self._subscribers[topic]:
                self._subscribers[topic].append(handler)

    async def unsubscribe(self, topic: str, handler: Callable[[Any], Any]):
        async with self._lock:
            if topic in self._subscribers and handler in self._subscribers[topic]:
                self._subscribers[topic].remove(handler)

    async def publish(self, topic: str, payload: Any):
        handlers = []
        async with self._lock:
            if topic in self._subscribers:
                handlers = list(self._subscribers[topic])
            # Check wildcard subscriptions e.g. "*"
            if "*" in self._subscribers:
                handlers.extend(self._subscribers["*"])

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(payload))
                else:
                    handler(payload)
            except Exception as e:
                logger.error(f"Error dispatching event to {handler} on topic {topic}: {e}")

# Global Event Bus Singleton
bus = EventBus()
