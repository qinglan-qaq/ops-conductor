<script setup lang="ts">
withDefaults(
  defineProps<{
    value: number
    label: string
    tone?: 'ink' | 'gold' | 'red'
  }>(),
  { tone: 'ink' },
)
</script>

<template>
  <div
    class="progress-bar"
    :class="`progress-bar--${tone}`"
    role="progressbar"
    :aria-valuenow="value"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-label="label"
  >
    <span class="progress-fill" :style="{ width: `${value}%` }" />
  </div>
</template>
