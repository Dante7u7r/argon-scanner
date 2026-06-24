use std::collections::HashMap;

static mut CACHE: Option<HashMap<String, String>> = None;

fn ensure_cache() -> &'static mut HashMap<String, String> {
    unsafe {
        if CACHE.is_none() {
            CACHE = Some(HashMap::new());
        }
        CACHE.as_mut().unwrap()
    }
}

pub fn cache_get(key: &str) -> Option<String> {
    ensure_cache().get(key).cloned()
}

pub fn cache_set(key: &str, value: &str) {
    ensure_cache().insert(key.to_string(), value.to_string());
}

pub fn cache_invalidate(key: &str) {
    ensure_cache().remove(key);
}
