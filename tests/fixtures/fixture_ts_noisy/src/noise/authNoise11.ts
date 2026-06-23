export function authenticateNoise11(token: string): boolean {
  return token.includes('auth-11');
}

export function loginNoise11(userId: string): string {
  return `login-noise-11:${userId}`;
}

export function sessionNoise11(sessionId: string): string {
  return `session-noise-11:${sessionId}`;
}
