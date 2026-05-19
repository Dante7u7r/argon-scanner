const store: Map<string, any> = new Map();

export function cacheGet(key: string): any {
  return store.get(key);
}

export function cacheSet(key: string, value: any, ttl: number = 3600): void {
  store.set(key, value);
}

export function cacheInvalidate(key: string): boolean {
  return store.delete(key);
}
