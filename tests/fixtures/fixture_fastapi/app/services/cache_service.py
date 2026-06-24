import json
from typing import Any, Optional

_cache = {}

def cache_get(key: str) -> Optional[Any]:
    return _cache.get(key)

def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    _cache[key] = value
    return True

def cache_invalidate(key: str) -> bool:
    if key in _cache:
        del _cache[key]
        return True
    return False

def cache_clear() -> int:
    count = len(_cache)
    _cache.clear()
    return count

def cache_get_many(keys: list) -> dict:
    return {k: _cache.get(k) for k in keys}
