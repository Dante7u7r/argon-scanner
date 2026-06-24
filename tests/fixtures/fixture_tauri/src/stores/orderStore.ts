import { defineStore } from 'pinia';
import { Order } from '../services/order';
import { placeOrder, cancelOrder } from '../services/order';
import { processPayment, refundPayment } from '../services/payment';

export const useOrderStore = defineStore('order', {
  state: () => ({
    currentOrder: null as Order | null,
    orders: [] as Order[],
  }),
  actions: {
    async createOrder(userId: string, items: number[]) {
      this.currentOrder = await placeOrder(userId, items);
      this.orders.push(this.currentOrder);
      return this.currentOrder;
    },
    async cancel(orderId: string) {
      return await cancelOrder(orderId);
    },
    async processPayment(order: Order) {
      return await processPayment(order);
    },
    async refundPayment(order: Order) {
      return await refundPayment(order);
    },
  },
});
