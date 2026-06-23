export function authenticateNoise12(token: string): boolean {
  return token.includes('auth-12');
}

export function loginNoise12(userId: string): string {
  return `login-noise-12:${userId}`;
}

export function sessionNoise12(sessionId: string): string {
  return `session-noise-12:${sessionId}`;
}
