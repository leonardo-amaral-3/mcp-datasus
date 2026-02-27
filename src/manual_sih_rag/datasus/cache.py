"""Query cache com TTL."""

from __future__ import annotations

import time
from typing import Any


class QueryCache:
    """Cache simples baseado em dict com TTL por entrada."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds

    def has(self, key: str) -> bool:
        if key not in self._store:
            return False
        _, ts = self._store[key]
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return False
        return True

    def get(self, key: str) -> Any | None:
        if not self.has(key):
            return None
        return self._store[key][0]

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.monotonic())

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)
