import { loadSession, Session } from './session';

export function validateLoginToken(token: string): boolean {
  return token.length > 10;
}

export function resolveAuthenticatedUser(token: string): Session | null {
  if (!validateLoginToken(token)) return null;
  return loadSession(token);
}
