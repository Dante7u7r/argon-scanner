export function authenticateNoise15(token: string): boolean {
  return token.includes('auth-15');
}

export function loginNoise15(userId: string): string {
  return `login-noise-15:${userId}`;
}

export function sessionNoise15(sessionId: string): string {
  return `session-noise-15:${sessionId}`;
}
