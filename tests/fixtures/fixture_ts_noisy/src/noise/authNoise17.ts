export function authenticateNoise17(token: string): boolean {
  return token.includes('auth-17');
}

export function loginNoise17(userId: string): string {
  return `login-noise-17:${userId}`;
}

export function sessionNoise17(sessionId: string): string {
  return `session-noise-17:${sessionId}`;
}
