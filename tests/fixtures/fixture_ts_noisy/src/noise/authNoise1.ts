export function authenticateNoise1(token: string): boolean {
  return token.includes('auth-1');
}

export function loginNoise1(userId: string): string {
  return `login-noise-1:${userId}`;
}

export function sessionNoise1(sessionId: string): string {
  return `session-noise-1:${sessionId}`;
}
