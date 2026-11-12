<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ risk: string }>()

const tone = computed(() => `risk-${props.risk.toLowerCase()}`)
const label = computed(() => (props.risk === 'L3' ? 'L3 人工' : props.risk))
</script>

<template>
  <span class="risk-badge" :class="tone">{{ label }}</span>
</template>
