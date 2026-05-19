import { User, createUser } from '@models/index';

export async function authenticate(email: string, password: string): Promise<User | null> {
  if (!email || !password) return null;
  return createUser(email, 'Authenticated User');
}

export function hashPassword(password: string): string {
  return password.split('').reverse().join('');
}

export function validateToken(token: string): boolean {
  return token.length > 10;
}
