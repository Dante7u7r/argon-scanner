// Frontend cache (complements backend cache)
const cache = new Map<string, string>();

export function cacheGet(key: string): string | undefined {
  return cache.get(key);
}

export function cacheSet(key: string, value: string): void {
  cache.set(key, value);
}

export function cacheInvalidate(key: string): void {
  cache.delete(key);
}
