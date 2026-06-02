import pytest
from app.services.payment_service import PaymentProcessor

def test_process_payment():
    processor = PaymentProcessor()
    result = processor.process_payment(order_id=1, amount=99.99)
    assert result["status"] == "completed"
    assert result["amount"] == 99.99
    assert "transaction_id" in result

def test_refund_payment():
    processor = PaymentProcessor()
    payment = processor.process_payment(order_id=1, amount=50.0)
    refund = processor.refund_payment(payment["transaction_id"])
    assert refund["status"] == "refunded"
    assert refund["amount"] == 50.0

def test_refund_payment_not_found():
    processor = PaymentProcessor()
    result = processor.refund_payment("nonexistent")
    assert result["status"] == "error"

def test_validate_amount():
    processor = PaymentProcessor()
    assert processor.validate_amount(100) is True
    assert processor.validate_amount(0) is False
    assert processor.validate_amount(-10) is False
    assert processor.validate_amount(200000) is False

def test_calculate_fee():
    processor = PaymentProcessor()
    fee = processor.calculate_fee(100, 2.9)
    assert fee == 2.9
