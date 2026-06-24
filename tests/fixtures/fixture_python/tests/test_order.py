from app.services.order_service import cancel_order, place_order


def test_place_order():
    result = place_order([10.0, 20.0, 30.0])
    assert result['total'] == 60.0
