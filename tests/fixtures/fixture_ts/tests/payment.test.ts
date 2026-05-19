import { processPayment, refundPayment } from '@lib/payment';

export function testProcessPayment() {
  const result = processPayment({ id: '1', userId: 'u1', total: 100 });
  return result.success === true;
}
