export interface User {
  id: string;
  email: string;
  name: string;
}

export function createUser(email: string, name: string): User {
  return { id: crypto.randomUUID(), email, name };
}
