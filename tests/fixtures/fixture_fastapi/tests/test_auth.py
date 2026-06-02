import pytest
from app.core.security import verify_password, get_password_hash, create_access_token, decode_access_token

def test_verify_password():
    password = "testpassword123"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_get_password_hash():
    password = "mypassword"
    hashed = get_password_hash(password)
    assert hashed != password
    assert len(hashed) > 0

def test_create_access_token():
    data = {"sub": "test@example.com"}
    token = create_access_token(data)
    assert len(token) > 0
    payload = decode_access_token(token)
    assert payload["sub"] == "test@example.com"

def test_decode_access_token_invalid():
    payload = decode_access_token("invalid-token")
    assert payload is None
