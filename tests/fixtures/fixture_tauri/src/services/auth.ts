import { invoke } from '@tauri-apps/api/core';

export interface User {
  id: string;
  email: string;
  name: string;
}

export interface CreateUserRequest {
  email: string;
  name: string;
}

export async function authenticate(email: string, password: string): Promise<User> {
  return await invoke('authenticate', { email, password });
}

export async function hashPassword(password: string): Promise<string> {
  return await invoke('hash_password', { password });
}

export async function validateToken(token: string): Promise<boolean> {
  return await invoke('validate_token', { token });
}
