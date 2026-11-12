<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ capability: string }>()

const domain = computed(() =>
  props.capability.startsWith('control.') ? 'control' : 'data',
)
</script>

<template>
  <span class="capability-badge" :class="`capability-badge--${domain}`">
    {{ capability }}
  </span>
</template>
