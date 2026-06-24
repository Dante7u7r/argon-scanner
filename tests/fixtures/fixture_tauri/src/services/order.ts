import { invoke } from '@tauri-apps/api/core';

export interface Order {
  id: string;
  user_id: string;
  total: number;
}

export interface CreateOrderRequest {
  user_id: string;
  items: number[];
}

export async function placeOrder(userId: string, items: number[]): Promise<Order> {
  return await invoke('place_order', { userId, items });
}

export async function cancelOrder(orderId: string): Promise<boolean> {
  return await invoke('cancel_order', { orderId });
}
