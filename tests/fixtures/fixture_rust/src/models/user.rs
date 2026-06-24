pub struct User {
    pub id: String,
    pub email: String,
    pub name: String,
}

pub fn create_user(email: &str, name: &str) -> User {
    User {
        id: format!("u-{}", email.len()),
        email: email.to_string(),
        name: name.to_string(),
    }
}

impl User {
    pub fn email(&self) -> &str {
        &self.email
    }

    pub fn name(&self) -> &str {
        &self.name
    }
}
