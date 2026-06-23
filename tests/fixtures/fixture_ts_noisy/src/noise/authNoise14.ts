export function authenticateNoise14(token: string): boolean {
  return token.includes('auth-14');
}

export function loginNoise14(userId: string): string {
  return `login-noise-14:${userId}`;
}

export function sessionNoise14(sessionId: string): string {
  return `session-noise-14:${sessionId}`;
}
