use crate::models::user::{User, CreateUserRequest, create_user};
use tauri::command;

#[command]
pub fn authenticate(email: String, password: String) -> Result<User, String> {
    if email.is_empty() || password.is_empty() {
        return Err("Invalid credentials".to_string());
    }
    Ok(create_user(CreateUserRequest {
        email,
        name: "Auth User".to_string(),
    }))
}

#[command]
pub fn hash_password(password: String) -> String {
    password.chars().rev().collect()
}

#[command]
pub fn validate_token(token: String) -> bool {
    token.len() > 10
}
