<script setup lang="ts">
defineProps<{ evidence: string[] }>()
</script>

<template>
  <ul class="evidence-list">
    <li v-for="entry in evidence" :key="entry">{{ entry }}</li>
  </ul>
</template>
