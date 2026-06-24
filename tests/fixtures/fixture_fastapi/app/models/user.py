from datetime import datetime

from app.core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="owner")

    def verify_password(self, plain_password: str) -> bool:
        from app.core.security import verify_password
        return verify_password(plain_password, self.hashed_password)

    def get_orders_count(self) -> int:
        return len(self.orders) if self.orders else 0
