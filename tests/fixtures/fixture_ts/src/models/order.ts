import { User } from './user';

export interface Order {
  id: string;
  userId: string;
  total: number;
}

export function calculateTotal(items: number[]): number {
  return items.reduce((sum, item) => sum + item, 0);
}
