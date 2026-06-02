from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default=OrderStatus.PENDING)
    total_amount = Column(Float, nullable=False)
    tax_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    final_amount = Column(Float, nullable=False)
    shipping_address = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")

    def calculate_total(self) -> float:
        subtotal = sum(item.price * item.quantity for item in self.items)
        self.tax_amount = subtotal * 0.18
        self.total_amount = subtotal
        self.final_amount = subtotal + self.tax_amount - self.discount_amount
        return self.final_amount

    def apply_discount(self, discount_percent: float) -> float:
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("Discount must be between 0 and 100")
        self.discount_amount = self.total_amount * (discount_percent / 100)
        self.final_amount = self.total_amount + self.tax_amount - self.discount_amount
        return self.final_amount

    def cancel(self) -> bool:
        if self.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            return False
        self.status = OrderStatus.CANCELLED
        return True

    def refund(self) -> bool:
        if self.status != OrderStatus.PAID:
            return False
        self.status = OrderStatus.REFUNDED
        return True

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
