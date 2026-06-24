import uuid
from decimal import Decimal
from typing import Optional


class PaymentProcessor:
    def __init__(self, api_key: str = "test-key"):
        self.api_key = api_key
        self.transactions = {}

    def process_payment(self, order_id: int, amount: float, currency: str = "USD") -> dict:
        transaction_id = str(uuid.uuid4())
        self.transactions[transaction_id] = {
            "order_id": order_id,
            "amount": amount,
            "currency": currency,
            "status": "completed",
        }
        return {"transaction_id": transaction_id, "status": "completed", "amount": amount}

    def refund_payment(self, transaction_id: str, amount: Optional[float] = None) -> dict:
        if transaction_id not in self.transactions:
            return {"status": "error", "message": "Transaction not found"}

        txn = self.transactions[transaction_id]
        refund_amount = amount or txn["amount"]
        txn["status"] = "refunded"
        return {"transaction_id": transaction_id, "status": "refunded", "amount": refund_amount}

    def get_transaction(self, transaction_id: str) -> Optional[dict]:
        return self.transactions.get(transaction_id)

    def validate_amount(self, amount: float) -> bool:
        return amount > 0 and amount <= 100000

    def calculate_fee(self, amount: float, fee_percent: float = 2.9) -> float:
        return round(amount * (fee_percent / 100), 2)
