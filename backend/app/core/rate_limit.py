"""Fixed-window rate limiter. Redis-backed; falls back to in-process memory if Redis is unreachable."""
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from app.core.config import settings

_memory: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
_redis = None
_redis_failed_at = 0.0


def _get_redis():
    global _redis, _redis_failed_at
    if _redis is not None:
        return _redis
    if time.time() - _redis_failed_at < 30 or not settings.redis_url:
        return None
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
        client.ping()
        _redis = client
        return client
    except Exception:
        _redis_failed_at = time.time()
        return None


def reset_memory_limits() -> None:
    _memory.clear()


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Record a hit; return True if still within the limit."""
    if not settings.rate_limit_enabled:
        return True
    client = _get_redis()
    if client is not None:
        try:
            rkey = f"rl:{key}:{int(time.time() // window_seconds)}"
            pipe = client.pipeline()
            pipe.incr(rkey)
            pipe.expire(rkey, window_seconds + 1)
            count = pipe.execute()[0]
            return count <= limit
        except Exception:
            pass
    count, start = _memory[key]
    now = time.time()
    if now - start >= window_seconds:
        count, start = 0, now
    count += 1
    _memory[key] = (count, start)
    return count <= limit


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_by_ip(scope: str, limit: int, window_seconds: int):
    """FastAPI dependency factory."""

    def dependency(request: Request) -> None:
        if not hit(f"{scope}:{client_ip(request)}", limit, window_seconds):
            raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")

    return dependency
