export function authenticateNoise5(token: string): boolean {
  return token.includes('auth-5');
}

export function loginNoise5(userId: string): string {
  return `login-noise-5:${userId}`;
}

export function sessionNoise5(sessionId: string): string {
  return `session-noise-5:${sessionId}`;
}
