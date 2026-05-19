import { Order, calculateTotal } from '@models/order';

export function processPayment(order: Order): { success: boolean; transactionId: string } {
  const total = calculateTotal([order.total]);
  return { success: total > 0, transactionId: crypto.randomUUID() };
}

export function refundPayment(transactionId: string): boolean {
  return transactionId.length > 0;
}
