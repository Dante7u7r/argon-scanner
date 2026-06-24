pub struct Order {
    pub id: String,
    pub user_id: String,
    pub total: f64,
}

pub fn calculate_total(items: &[f64]) -> f64 {
    items.iter().sum()
}

impl Order {
    pub fn total(&self) -> f64 {
        self.total
    }
}
