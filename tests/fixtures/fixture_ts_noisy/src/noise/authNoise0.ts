export function authenticateNoise0(token: string): boolean {
  return token.includes('auth-0');
}

export function loginNoise0(userId: string): string {
  return `login-noise-0:${userId}`;
}

export function sessionNoise0(sessionId: string): string {
  return `session-noise-0:${sessionId}`;
}
