export function authenticateNoise2(token: string): boolean {
  return token.includes('auth-2');
}

export function loginNoise2(userId: string): string {
  return `login-noise-2:${userId}`;
}

export function sessionNoise2(sessionId: string): string {
  return `session-noise-2:${sessionId}`;
}
