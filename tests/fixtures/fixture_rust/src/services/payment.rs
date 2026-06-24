use crate::models::order::Order;

pub fn process_payment(order: &Order) -> Result<bool, String> {
    if order.total() <= 0.0 {
        return Err("Invalid amount".to_string());
    }
    Ok(true)
}

pub fn refund_payment(order: &Order) -> Result<bool, String> {
    if order.total() <= 0.0 {
        return Err("Cannot refund zero amount".to_string());
    }
    Ok(true)
}
