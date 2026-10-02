"""Limits that cap the damage when something else goes wrong.

They do not keep anyone out; they bound the worst case. A bug in the agent's retry loop, or a
caller holding a valid token, can then waste at most a small, known amount of search credits.

  - RateLimiter:  at most N tool calls per minute per user (protects against floods and loops).
  - CreditLedger: at most N paid search calls per day per user, and M per day for everyone.

State is kept in this process's memory. Several copies of the server would each have their own
counters, so before scaling out these move to a shared store such as Redis.
"""

import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta


class LimitExceeded(Exception):
    def __init__(self, message: str, retry_after_s: int):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class RateLimiter:
    """Sliding window: a call is refused if the user already made `per_minute` calls in the last 60 s."""

    def __init__(self, per_minute: int, clock=time.time):
        self.per_minute, self._clock = per_minute, clock
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    def check(self, subject: str) -> None:
        now = self._clock()
        calls = self._calls[subject]
        while calls and calls[0] <= now - 60:
            calls.popleft()
        if len(calls) >= self.per_minute:
            wait = max(1, int(calls[0] + 60 - now) + 1)
            raise LimitExceeded(f"Too many requests. Try again in {wait} seconds.", wait)
        calls.append(now)


class CreditLedger:
    """Counts paid provider calls per UTC day, per user and in total. Refuses over the cap."""

    def __init__(self, per_user_daily: int, global_daily: int, clock=time.time):
        self.per_user, self.global_cap, self._clock = per_user_daily, global_daily, clock
        self._day = self._today()
        self._users: dict[str, int] = defaultdict(int)
        self._total = 0

    def _today(self):
        return datetime.fromtimestamp(self._clock(), UTC).date()

    def _roll_over(self) -> None:
        if self._today() != self._day:
            self._day, self._users, self._total = self._today(), defaultdict(int), 0

    def _seconds_to_reset(self) -> int:
        tomorrow = datetime.combine(self._day + timedelta(days=1), datetime.min.time(), UTC)
        return max(1, int(tomorrow.timestamp() - self._clock()))

    def spend(self, subject: str, credits: int = 1) -> None:
        self._roll_over()
        if self._total + credits > self.global_cap:
            raise LimitExceeded(
                "The daily search budget for the whole service is used up. It resets at 00:00 UTC.",
                self._seconds_to_reset(),
            )
        if self._users[subject] + credits > self.per_user:
            raise LimitExceeded(
                "You have used today's search allowance. It resets at 00:00 UTC.", self._seconds_to_reset()
            )
        self._users[subject] += credits
        self._total += credits

    @property
    def used_today(self) -> int:
        self._roll_over()
        return self._total
