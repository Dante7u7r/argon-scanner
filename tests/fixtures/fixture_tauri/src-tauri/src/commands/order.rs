use crate::models::order::{Order, CreateOrderRequest, create_order, calculate_total};
use crate::utils::cache::{cache_get, cache_set};
use tauri::command;

#[command]
pub fn place_order(user_id: String, items: Vec<f64>) -> Result<Order, String> {
    let req = CreateOrderRequest { user_id, items };
    let order = create_order(req);
    cache_set(&format!("order:{}", order.id), &order.id);
    Ok(order)
}

#[command]
pub fn cancel_order(order_id: String) -> bool {
    let key = format!("order:{}", order_id);
    cache_get(&key).is_some()
}
