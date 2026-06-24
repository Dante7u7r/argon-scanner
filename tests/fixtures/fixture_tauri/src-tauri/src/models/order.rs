use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: String,
    pub user_id: String,
    pub total: f64,
}

#[derive(Debug, Deserialize)]
pub struct CreateOrderRequest {
    pub user_id: String,
    pub items: Vec<f64>,
}

pub fn calculate_total(items: &[f64]) -> f64 {
    items.iter().sum()
}

pub fn create_order(req: CreateOrderRequest) -> Order {
    Order {
        id: format!("o-{}", req.items.len()),
        user_id: req.user_id,
        total: calculate_total(&req.items),
    }
}

impl Order {
    pub fn total(&self) -> f64 {
        self.total
    }
}
