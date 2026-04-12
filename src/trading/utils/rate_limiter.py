"""Thread-safe rate limiter for API calls."""

import threading
import time
from collections import deque
from typing import Callable, TypeVar

T = TypeVar("T")


class RateLimiter:
    """Thread-safe rate limiter using sliding window."""

    def __init__(self, max_calls: int, period_seconds: float):
        """Initialize rate limiter.

        Args:
            max_calls: Maximum number of calls allowed in the period.
            period_seconds: Time period in seconds.
        """
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Acquire permission to make a call, blocking if necessary."""
        with self._lock:
            now = time.monotonic()
            self._cleanup(now)

            if len(self._calls) >= self.max_calls:
                oldest = self._calls[0]
                sleep_time = self.period_seconds - (now - oldest)
                if sleep_time > 0:
                    # Release lock while sleeping
                    self._lock.release()
                    try:
                        time.sleep(sleep_time)
                    finally:
                        self._lock.acquire()
                    now = time.monotonic()
                    self._cleanup(now)

            self._calls.append(now)

    def _cleanup(self, now: float) -> None:
        """Remove expired timestamps from the window."""
        cutoff = now - self.period_seconds
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()

    def try_acquire(self) -> bool:
        """Try to acquire permission without blocking.

        Returns:
            True if acquired, False if rate limit would be exceeded.
        """
        with self._lock:
            now = time.monotonic()
            self._cleanup(now)

            if len(self._calls) >= self.max_calls:
                return False

            self._calls.append(now)
            return True

    def remaining(self) -> int:
        """Get remaining calls available in current window."""
        with self._lock:
            self._cleanup(time.monotonic())
            return max(0, self.max_calls - len(self._calls))

    def reset(self) -> None:
        """Reset the rate limiter."""
        with self._lock:
            self._calls.clear()


def rate_limited(limiter: RateLimiter) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to apply rate limiting to a function.

    Args:
        limiter: RateLimiter instance to use.

    Returns:
        Decorated function that respects rate limits.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            limiter.acquire()
            return func(*args, **kwargs)

        return wrapper

    return decorator


# Pre-configured rate limiters for common APIs
UPBIT_RATE_LIMITER = RateLimiter(max_calls=10, period_seconds=1.0)  # 10 req/sec
CMC_RATE_LIMITER = RateLimiter(max_calls=30, period_seconds=60.0)  # 30 req/min
