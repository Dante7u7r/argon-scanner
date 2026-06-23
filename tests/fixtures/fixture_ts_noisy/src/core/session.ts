export interface Session {
  userId: string;
  token: string;
}

export function loadSession(token: string): Session | null {
  if (!token) return null;
  return { userId: 'u1', token };
}
