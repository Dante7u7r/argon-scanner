_store: dict = {}

def cache_get(key: str):
    return _store.get(key)

def cache_set(key: str, value, ttl: int = 3600):
    _store[key] = value

def cache_invalidate(key: str) -> bool:
    return _store.pop(key, None) is not None
