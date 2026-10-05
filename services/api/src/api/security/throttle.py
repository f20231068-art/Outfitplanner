"""Limits on how fast one caller may do something. They cap damage from floods and guessing.

State is in this process's memory. With several copies of the API each has its own counters, so
before scaling out these move to a shared store such as Redis.
"""

import time
from collections import defaultdict, deque


class TooManyAttempts(Exception):
    def __init__(self, retry_after_s: int):
        super().__init__(f"Too many attempts. Try again in {retry_after_s} seconds.")
        self.retry_after_s = retry_after_s


class SlidingWindow:
    """At most `limit` events per `window_s` seconds per key (0 = unlimited). check() records the event."""

    def __init__(self, limit: int, window_s: int, clock=time.time):
        self.limit, self.window_s, self._clock = limit, window_s, clock
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> deque[float]:
        events = self._events[key]
        while events and events[0] <= now - self.window_s:
            events.popleft()
        return events

    def check(self, key: str) -> None:
        if self.limit <= 0:  # 0 = no limit
            return
        now = self._clock()
        events = self._trim(key, now)
        if len(events) >= self.limit:
            raise TooManyAttempts(max(1, int(events[0] + self.window_s - now) + 1))
        events.append(now)


class FailureCounter:
    """Counts FAILED attempts only (wrong passwords). Success clears the count. Used for logins:
    five wrong guesses for one email from one address lock that pair out for the window."""

    def __init__(self, max_failures: int, window_s: int, clock=time.time):
        self.max_failures, self.window_s, self._clock = max_failures, window_s, clock
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str) -> deque[float]:
        now = self._clock()
        fails = self._fails[key]
        while fails and fails[0] <= now - self.window_s:
            fails.popleft()
        return fails

    def ensure_allowed(self, key: str) -> None:
        fails = self._trim(key)
        if len(fails) >= self.max_failures:
            raise TooManyAttempts(max(1, int(fails[0] + self.window_s - self._clock()) + 1))

    def record_failure(self, key: str) -> None:
        self._trim(key).append(self._clock())

    def clear(self, key: str) -> None:
        self._fails.pop(key, None)
