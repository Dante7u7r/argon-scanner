export function authenticateNoise13(token: string): boolean {
  return token.includes('auth-13');
}

export function loginNoise13(userId: string): string {
  return `login-noise-13:${userId}`;
}

export function sessionNoise13(sessionId: string): string {
  return `session-noise-13:${sessionId}`;
}
