use fixture_rust::services::auth::{authenticate, hash_password};

#[test]
fn test_authenticate() {
    let user = authenticate("a@b.com", "secret").unwrap();
    assert_eq!(user.email(), "a@b.com");
}

#[test]
fn test_hash_password() {
    let hashed = hash_password("abc");
    assert_eq!(hashed, "cba");
}
