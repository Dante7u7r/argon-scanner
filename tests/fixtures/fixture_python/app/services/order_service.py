from ..models.order import Order, calculate_total
from ..utils.cache import cache_get, cache_set

def place_order(items: list) -> dict:
    total = calculate_total(items)
    order = Order(id='o1', user_id='u1', total=total)
    cache_set(f'order:{order.id}', order)
    return {'order_id': order.id, 'total': total}

def cancel_order(order_id: str) -> bool:
    cached = cache_get(f'order:{order_id}')
    return cached is not None
