export function authenticateNoise4(token: string): boolean {
  return token.includes('auth-4');
}

export function loginNoise4(userId: string): string {
  return `login-noise-4:${userId}`;
}

export function sessionNoise4(sessionId: string): string {
  return `session-noise-4:${sessionId}`;
}
