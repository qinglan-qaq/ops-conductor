<script setup lang="ts">
defineProps<{ freshness: string }>()
</script>

<template>
  <span class="freshness" :class="`freshness--${freshness}`">
    {{ freshness }}
  </span>
</template>
