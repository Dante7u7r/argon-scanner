use crate::models::order::{Order, calculate_total};
use crate::utils::cache::{cache_get, cache_set};

pub fn place_order(items: &[f64]) -> Order {
    let total = calculate_total(items);
    let order = Order {
        id: "o1".to_string(),
        user_id: "u1".to_string(),
        total,
    };
    cache_set(&format!("order:{}", order.id), &order.id);
    order
}

pub fn cancel_order(order_id: &str) -> bool {
    let key = format!("order:{}", order_id);
    cache_get(&key).is_some()
}
