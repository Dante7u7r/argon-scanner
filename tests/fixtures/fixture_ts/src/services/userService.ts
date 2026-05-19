import { authenticate, validateToken } from '@lib/auth';
import { User } from '@models/user';

export async function loginUser(email: string, password: string): Promise<User | null> {
  return authenticate(email, password);
}

export function checkSession(token: string): boolean {
  return validateToken(token);
}
