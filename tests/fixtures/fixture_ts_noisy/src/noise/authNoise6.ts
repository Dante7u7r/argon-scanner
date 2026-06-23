export function authenticateNoise6(token: string): boolean {
  return token.includes('auth-6');
}

export function loginNoise6(userId: string): string {
  return `login-noise-6:${userId}`;
}

export function sessionNoise6(sessionId: string): string {
  return `session-noise-6:${sessionId}`;
}
