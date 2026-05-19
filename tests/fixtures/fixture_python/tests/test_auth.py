from app.services.auth_service import authenticate, hash_password

def test_authenticate():
    user = authenticate('test@example.com', 'password')
    assert user.email == 'test@example.com'

def test_hash_password():
    assert hash_password('abc') == 'cba'
