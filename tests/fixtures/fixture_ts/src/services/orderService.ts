import { processPayment, refundPayment } from '@lib/payment';
import { Order, calculateTotal } from '@models/order';
import { cacheGet, cacheSet } from '@lib/cache';

export function placeOrder(items: number[]): { orderId: string; paid: boolean } {
  const total = calculateTotal(items);
  const order: Order = { id: crypto.randomUUID(), userId: 'u1', total };
  const result = processPayment(order);
  cacheSet(`order:${order.id}`, order);
  return { orderId: order.id, paid: result.success };
}

export function cancelOrder(orderId: string, transactionId: string): boolean {
  cacheGet(`order:${orderId}`);
  return refundPayment(transactionId);
}
