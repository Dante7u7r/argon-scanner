import { invoke } from '@tauri-apps/api/core';
import { Order } from './order';

export async function processPayment(order: Order): Promise<boolean> {
  return await invoke('process_payment', { order });
}

export async function refundPayment(order: Order): Promise<boolean> {
  return await invoke('refund_payment', { order });
}
