from app.models.order import Order, OrderItem
from sqlalchemy.orm import Session


def get_order(db: Session, order_id: int) -> Order:
    return db.query(Order).filter(Order.id == order_id).first()

def get_user_orders(db: Session, user_id: int) -> list:
    return db.query(Order).filter(Order.user_id == user_id).all()

def create_order(db: Session, user_id: int, items: list) -> Order:
    order = Order(user_id=user_id)
    db.add(order)
    db.flush()

    for item_data in items:
        item = OrderItem(
            order_id=order.id,
            product_name=item_data["product_name"],
            price=item_data["price"],
            quantity=item_data["quantity"],
        )
        db.add(item)

    order.calculate_total()
    db.commit()
    db.refresh(order)
    return order

def update_order_status(db: Session, order: Order, status: str) -> Order:
    order.status = status
    db.commit()
    db.refresh(order)
    return order

def delete_order(db: Session, order_id: int) -> bool:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        db.delete(order)
        db.commit()
        return True
    return False
