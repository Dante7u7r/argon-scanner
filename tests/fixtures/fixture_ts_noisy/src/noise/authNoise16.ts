export function authenticateNoise16(token: string): boolean {
  return token.includes('auth-16');
}

export function loginNoise16(userId: string): string {
  return `login-noise-16:${userId}`;
}

export function sessionNoise16(sessionId: string): string {
  return `session-noise-16:${sessionId}`;
}
