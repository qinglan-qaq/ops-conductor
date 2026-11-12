<script setup lang="ts">
withDefaults(
  defineProps<{
    text: string
    tone?: 'approve' | 'reject' | 'pending'
  }>(),
  { tone: 'pending' },
)
</script>

<template>
  <span class="seal" :class="`seal--${tone}`" aria-hidden="true">{{ text }}</span>
</template>
