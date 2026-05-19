package com.app.services;

import com.app.models.Order;

public interface PaymentService {
    boolean processPayment(Order order);
    boolean refundPayment(String transactionId);
}
