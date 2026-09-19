"""CYBER SWARM TRADING OS - Async Event Bus"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("cyber_swarm.event_bus")


class EventBus:
    """Thread-safe and async-safe pub/sub event bus with background task tracking."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Any], Any]]] = {}
        self._lock: asyncio.Lock | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def _get_lock(self) -> asyncio.Lock:
        """Lazily initializes the asyncio.Lock within the active running event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def subscribe(self, topic: str, handler: Callable[[Any], Any]) -> None:
        """Subscribes a callable handler (sync or async) to a specific topic or wildcard '*'."""
        async with self._get_lock():
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            if handler not in self._subscribers[topic]:
                self._subscribers[topic].append(handler)

    async def unsubscribe(self, topic: str, handler: Callable[[Any], Any]) -> None:
        """Unsubscribes a handler from a given topic."""
        async with self._get_lock():
            if topic in self._subscribers and handler in self._subscribers[topic]:
                self._subscribers[topic].remove(handler)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]

    async def publish(self, topic: str, payload: Any) -> None:
        """Publishes a payload to all matching topic handlers and wildcard '*' subscribers."""
        handlers: list[Callable[[Any], Any]] = []
        async with self._get_lock():
            if topic in self._subscribers:
                handlers.extend(self._subscribers[topic])
            if "*" in self._subscribers and topic != "*":
                handlers.extend(self._subscribers["*"])

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    task = asyncio.create_task(handler(payload))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                else:
                    handler(payload)
            except Exception as e:
                logger.error(
                    f"Error dispatching event to {handler} on topic {topic}: {e}",
                    exc_info=True,
                )

    def get_subscriber_count(self, topic: str | None = None) -> int:
        """Returns the count of subscribers for a topic, or across all topics."""
        if topic is not None:
            return len(self._subscribers.get(topic, []))
        return sum(len(h) for h in self._subscribers.values())


# Global Event Bus Singleton
bus = EventBus()
