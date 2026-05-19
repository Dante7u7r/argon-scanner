package com.app.services;

import com.app.models.Order;

public class OrderService {
    public Order placeOrder(double[] items) {
        double total = Order.calculateTotal(items);
        return new Order("o1", "u1", total);
    }

    public boolean cancelOrder(String orderId) {
        return orderId != null;
    }
}
