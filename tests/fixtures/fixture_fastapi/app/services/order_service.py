from sqlalchemy.orm import Session
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.order import OrderCreate
from app.services.cache_service import cache_get, cache_set, cache_invalidate

def create_order(db: Session, user_id: int, order_in: OrderCreate) -> Order:
    order = Order(user_id=user_id, shipping_address=order_in.shipping_address)
    db.add(order)
    db.flush()

    for item_in in order_in.items:
        item = OrderItem(
            order_id=order.id,
            product_name=item_in.product_name,
            price=item_in.price,
            quantity=item_in.quantity,
        )
        db.add(item)

    order.calculate_total()
    if order_in.discount_code:
        apply_discount_code(order, order_in.discount_code)

    db.commit()
    db.refresh(order)
    cache_set(f"order:{order.id}", order.final_amount)
    return order

def get_order(db: Session, order_id: int) -> Order:
    cached = cache_get(f"order:{order_id}")
    if cached is not None:
        return cached
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        cache_set(f"order:{order.id}", order)
    return order

def cancel_order(db: Session, order: Order, reason: str = None) -> bool:
    if not order.cancel():
        return False
    db.commit()
    cache_invalidate(f"order:{order.id}")
    return True

def refund_order(db: Session, order: Order, reason: str) -> bool:
    if not order.refund():
        return False
    db.commit()
    cache_invalidate(f"order:{order.id}")
    return True

def get_user_orders(db: Session, user_id: int) -> list:
    return db.query(Order).filter(Order.user_id == user_id).all()

def apply_discount_code(order: Order, code: str) -> float:
    discount_map = {"WELCOME10": 10, "SUMMER20": 20, "VIP50": 50}
    discount = discount_map.get(code, 0)
    if discount > 0:
        order.apply_discount(discount)
    return discount

def get_order_statistics(db: Session, user_id: int) -> dict:
    orders = get_user_orders(db, user_id)
    total_spent = sum(o.final_amount for o in orders)
    avg_order = total_spent / len(orders) if orders else 0
    return {
        "total_orders": len(orders),
        "total_spent": total_spent,
        "average_order": avg_order,
    }
