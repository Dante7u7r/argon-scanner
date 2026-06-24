mod models;
mod services;
mod utils;

fn main() {
    let order = services::order::place_order(&[10.0, 20.0, 5.0]);
    println!("Order total: {}", order.total());
}
