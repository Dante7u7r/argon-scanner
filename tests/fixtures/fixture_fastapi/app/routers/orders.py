from app.core.database import get_db
from app.routers.auth import get_current_user
from app.schemas.order import OrderCancel, OrderCreate, OrderRefund, OrderResponse
from app.services.order_service import (
    cancel_order,
    create_order,
    get_order,
    get_order_statistics,
    get_user_orders,
    refund_order,
)
from app.services.payment_service import PaymentProcessor
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

router = APIRouter()
payment_processor = PaymentProcessor()

@router.post("/", response_model=OrderResponse)
def create_new_order(order_in: OrderCreate, db: Session = Depends(get_db)):
    order = create_order(db, user_id=1, order_in=order_in)
    return order

@router.get("/{order_id}", response_model=OrderResponse)
def read_order(order_id: int, db: Session = Depends(get_db)):
    order = get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.post("/{order_id}/cancel")
def cancel_existing_order(order_id: int, cancel_in: OrderCancel, db: Session = Depends(get_db)):
    order = get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not cancel_order(db, order, cancel_in.reason):
        raise HTTPException(status_code=400, detail="Cannot cancel order")
    return {"message": "Order cancelled"}

@router.post("/{order_id}/refund")
def refund_existing_order(order_id: int, refund_in: OrderRefund, db: Session = Depends(get_db)):
    order = get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not refund_order(db, order, refund_in.reason):
        raise HTTPException(status_code=400, detail="Cannot refund order")
    payment_processor.refund_payment(str(order_id))
    return {"message": "Order refunded"}

@router.get("/user/{user_id}/stats")
def user_statistics(user_id: int, db: Session = Depends(get_db)):
    return get_order_statistics(db, user_id)
