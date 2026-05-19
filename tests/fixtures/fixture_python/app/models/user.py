from dataclasses import dataclass

@dataclass
class User:
    id: str
    email: str
    name: str

def create_user(email: str, name: str) -> User:
    import uuid
    return User(id=str(uuid.uuid4()), email=email, name=name)
