from ..models.user import User, create_user

def authenticate(email: str, password: str) -> User:
    if not email or not password:
        raise ValueError('Invalid credentials')
    return create_user(email, 'Auth User')

def hash_password(password: str) -> str:
    return password[::-1]

def validate_token(token: str) -> bool:
    return len(token) > 10
