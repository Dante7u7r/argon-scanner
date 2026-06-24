<script setup lang="ts">
import { useOrderStore } from '../stores/orderStore';
import { ref } from 'vue';

const orderStore = useOrderStore();
const userId = ref('user-123');
const items = ref<number[]>([10, 20, 5]);

async function createOrder() {
  await orderStore.createOrder(userId.value, items.value);
}

async function processPayment() {
  if (orderStore.currentOrder) {
    await orderStore.processPayment(orderStore.currentOrder);
  }
}
</script>

<template>
  <div>
    <h2>Order: {{ currentOrder?.id }}</h2>
    <p>Total: {{ currentOrder?.total }}</p>
    <button @click="createOrder">Create Order</button>
    <button @click="processPayment" v-if="currentOrder">Process Payment</button>
  </div>
</template>
