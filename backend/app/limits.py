import hashlib
import time
from collections import defaultdict
from functools import lru_cache
from threading import Lock

import redis
from fastapi import HTTPException, Request

from app.config import get_settings

_buckets: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


@lru_cache
def redis_client():
    return redis.Redis.from_url(
        get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2
    )


def limit(request: Request, action: str, maximum: int):
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    address = request.client.host if request.client else "unknown"
    key = "attendance:rate:" + hashlib.sha256(f"{action}:{address}".encode()).hexdigest()
    if settings.redis_url:
        try:
            count = redis_client().eval(
                "local n=redis.call('INCR',KEYS[1]); "
                "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
                1,
                key,
            )
        except redis.RedisError as exc:
            raise HTTPException(503, "服务暂时不可用，请稍后重试") from exc
    else:
        with _lock:
            now = time.monotonic()
            # Bound storage even when many client addresses appear during local development.
            for old_key in list(_buckets):
                if not _buckets[old_key] or _buckets[old_key][-1] <= now - 60:
                    del _buckets[old_key]
            values = [v for v in _buckets[key] if v > now - 60]
            values.append(now)
            _buckets[key] = values[-(maximum + 1) :]
            count = len(values)
    if count > maximum:
        raise HTTPException(429, "操作频繁，请一分钟后重试", headers={"Retry-After": "60"})
