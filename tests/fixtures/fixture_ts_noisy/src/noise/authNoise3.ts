export function authenticateNoise3(token: string): boolean {
  return token.includes('auth-3');
}

export function loginNoise3(userId: string): string {
  return `login-noise-3:${userId}`;
}

export function sessionNoise3(sessionId: string): string {
  return `session-noise-3:${sessionId}`;
}
