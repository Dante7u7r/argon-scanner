import { defineStore } from 'pinia';
import { User } from '../services/auth';
import { authenticate, hashPassword, validateToken } from '../services/auth';

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    token: '',
  }),
  actions: {
    async login(email: string, password: string) {
      this.user = await authenticate(email, password);
    },
    async verifyToken(token: string) {
      return await validateToken(token);
    },
  },
});
