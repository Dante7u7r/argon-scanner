import { authenticate, hashPassword, validateToken } from '@lib/auth';

export async function testAuthenticate() {
  const user = await authenticate('test@example.com', 'password');
  return user !== null;
}

export function testHashPassword() {
  return hashPassword('abc') === 'cba';
}
