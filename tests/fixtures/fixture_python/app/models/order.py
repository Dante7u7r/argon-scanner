from dataclasses import dataclass
from typing import List


@dataclass
class Order:
    id: str
    user_id: str
    total: float

def calculate_total(items: List[float]) -> float:
    return sum(items)
