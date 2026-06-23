export function authenticateNoise7(token: string): boolean {
  return token.includes('auth-7');
}

export function loginNoise7(userId: string): string {
  return `login-noise-7:${userId}`;
}

export function sessionNoise7(sessionId: string): string {
  return `session-noise-7:${sessionId}`;
}
