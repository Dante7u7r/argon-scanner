export function authenticateNoise9(token: string): boolean {
  return token.includes('auth-9');
}

export function loginNoise9(userId: string): string {
  return `login-noise-9:${userId}`;
}

export function sessionNoise9(sessionId: string): string {
  return `session-noise-9:${sessionId}`;
}
