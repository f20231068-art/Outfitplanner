"""Tiny in-memory TTL cache. Fine for one server process; swap for Redis when we run several."""

import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_s: int, max_items: int = 1000):
        self.ttl_s, self.max_items = ttl_s, max_items
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._data) >= self.max_items:  # drop the oldest entry
            self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic() + self.ttl_s, value)
