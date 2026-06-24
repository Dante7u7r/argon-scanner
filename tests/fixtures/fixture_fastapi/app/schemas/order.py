from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class OrderItemCreate(BaseModel):
    product_name: str
    price: float
    quantity: int

class OrderItemResponse(OrderItemCreate):
    id: int

    class Config:
        from_attributes = True

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    shipping_address: str
    discount_code: Optional[str] = None

class OrderResponse(BaseModel):
    id: int
    status: str
    total_amount: float
    tax_amount: float
    discount_amount: float
    final_amount: float
    items: List[OrderItemResponse]
    created_at: datetime

    class Config:
        from_attributes = True

class OrderCancel(BaseModel):
    reason: Optional[str] = None

class OrderRefund(BaseModel):
    reason: str
    amount: Optional[float] = None
