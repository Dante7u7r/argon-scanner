export function authenticateNoise8(token: string): boolean {
  return token.includes('auth-8');
}

export function loginNoise8(userId: string): string {
  return `login-noise-8:${userId}`;
}

export function sessionNoise8(sessionId: string): string {
  return `session-noise-8:${sessionId}`;
}
