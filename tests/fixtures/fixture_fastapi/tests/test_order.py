import pytest
from app.models.order import Order, OrderItem, OrderStatus
from app.services.order_service import apply_discount_code, get_order_statistics


def test_order_calculate_total():
    order = Order()
    order.items = [
        OrderItem(price=10.0, quantity=2),
        OrderItem(price=20.0, quantity=1),
    ]
    total = order.calculate_total()
    assert total == 40.0  # (10*2 + 20*1) * 1.18

def test_order_apply_discount():
    order = Order()
    order.items = [OrderItem(price=100.0, quantity=1)]
    order.calculate_total()
    final = order.apply_discount(10)
    assert final == 106.2  # 100 + 18 - 10

def test_order_apply_discount_invalid():
    order = Order()
    order.items = [OrderItem(price=100.0, quantity=1)]
    order.calculate_total()
    with pytest.raises(ValueError):
        order.apply_discount(150)

def test_order_cancel():
    order = Order(status=OrderStatus.PENDING)
    assert order.cancel() is True
    assert order.status == OrderStatus.CANCELLED

def test_order_cancel_shipped():
    order = Order(status=OrderStatus.SHIPPED)
    assert order.cancel() is False

def test_order_refund():
    order = Order(status=OrderStatus.PAID)
    assert order.refund() is True
    assert order.status == OrderStatus.REFUNDED

def test_order_refund_pending():
    order = Order(status=OrderStatus.PENDING)
    assert order.refund() is False

def test_apply_discount_code():
    order = Order()
    order.items = [OrderItem(price=100.0, quantity=1)]
    order.calculate_total()
    discount = apply_discount_code(order, "WELCOME10")
    assert discount == 10

def test_apply_discount_code_invalid():
    order = Order()
    order.items = [OrderItem(price=100.0, quantity=1)]
    order.calculate_total()
    discount = apply_discount_code(order, "INVALID")
    assert discount == 0
