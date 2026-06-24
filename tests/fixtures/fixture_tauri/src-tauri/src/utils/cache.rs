use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};

static CACHE: LazyLock<Mutex<HashMap<String, String>>> = LazyLock::new(|| Mutex::new(HashMap::new()));

pub fn cache_get(key: &str) -> Option<String> {
    CACHE.lock().unwrap().get(key).cloned()
}

pub fn cache_set(key: &str, value: &str) {
    CACHE.lock().unwrap().insert(key.to_string(), value.to_string());
}

pub fn cache_invalidate(key: &str) {
    CACHE.lock().unwrap().remove(key);
}
