<script setup lang="ts">
import { useToast } from '@/composables/useToast'

const toast = useToast()
</script>

<template>
  <div
    class="toast"
    :class="[toast.kind.value, { 'is-visible': toast.visible.value }]"
    role="status"
    aria-live="polite"
  >
    {{ toast.message.value }}
  </div>
</template>
