from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window = timedelta(seconds=window_seconds)
        self.attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self.lock = Lock()

    def is_limited(self, key: str) -> bool:
        with self.lock:
            self._cleanup(key)
            return len(self.attempts[key]) >= self.max_attempts

    def register_attempt(self, key: str) -> None:
        with self.lock:
            self._cleanup(key)
            self.attempts[key].append(datetime.utcnow())

    def reset(self, key: str) -> None:
        with self.lock:
            self.attempts.pop(key, None)

    def _cleanup(self, key: str) -> None:
        cutoff = datetime.utcnow() - self.window
        q = self.attempts[key]
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            self.attempts.pop(key, None)


class SlidingWindowRateLimiter(LoginRateLimiter):
    pass
