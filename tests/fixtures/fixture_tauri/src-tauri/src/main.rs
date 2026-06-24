mod models;
mod commands;
mod utils;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::auth::authenticate,
            commands::auth::hash_password,
            commands::auth::validate_token,
            commands::order::place_order,
            commands::order::cancel_order,
            commands::payment::process_payment,
            commands::payment::refund_payment,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
