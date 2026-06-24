<script setup lang="ts">
import { useAuthStore } from '../stores/authStore';
import { ref } from 'vue';

const authStore = useAuthStore();
const email = ref('');
const password = ref('');

async function handleLogin() {
  try {
    await authStore.login(email.value, password.value);
  } catch (error) {
    console.error('Login failed:', error);
  }
}
</script>

<template>
  <form @submit.prevent="handleLogin">
    <input v-model="email" type="email" placeholder="Email" required />
    <input v-model="password" type="password" placeholder="Password" required />
    <button type="submit">Login</button>
  </form>
</template>
