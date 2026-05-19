package com.app.models;

public class Order {
    private String id;
    private String userId;
    private double total;

    public Order(String id, String userId, double total) {
        this.id = id;
        this.userId = userId;
        this.total = total;
    }

    public double getTotal() { return total; }

    public static double calculateTotal(double[] items) {
        double sum = 0;
        for (double item : items) sum += item;
        return sum;
    }
}
