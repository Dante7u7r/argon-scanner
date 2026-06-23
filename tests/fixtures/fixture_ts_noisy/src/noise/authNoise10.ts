export function authenticateNoise10(token: string): boolean {
  return token.includes('auth-10');
}

export function loginNoise10(userId: string): string {
  return `login-noise-10:${userId}`;
}

export function sessionNoise10(sessionId: string): string {
  return `session-noise-10:${sessionId}`;
}
