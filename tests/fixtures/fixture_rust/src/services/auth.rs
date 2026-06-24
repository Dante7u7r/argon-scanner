use crate::models::user::{User, create_user};

pub fn authenticate(email: &str, password: &str) -> Result<User, String> {
    if email.is_empty() || password.is_empty() {
        return Err("Invalid credentials".to_string());
    }
    Ok(create_user(email, "Auth User"))
}

pub fn hash_password(password: &str) -> String {
    password.chars().rev().collect()
}

pub fn validate_token(token: &str) -> bool {
    token.len() > 10
}
