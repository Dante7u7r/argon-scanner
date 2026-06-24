from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import UserCreate
from sqlalchemy.orm import Session


def get_user_by_email(db: Session, email: str) -> User:
    return db.query(User).filter(User.email == email).first()

def get_user_by_id(db: Session, user_id: int) -> User:
    return db.query(User).filter(User.id == user_id).first()

def create_user(db: Session, user_in: UserCreate) -> User:
    db_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

def update_user_profile(db: Session, user: User, full_name: str = None) -> User:
    if full_name:
        user.full_name = full_name
    db.commit()
    db.refresh(user)
    return user

def deactivate_user(db: Session, user: User) -> bool:
    user.is_active = False
    db.commit()
    return True
