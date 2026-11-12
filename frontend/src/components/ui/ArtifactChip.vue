<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ name: string; kind: string }>()

const kindLabel: Record<string, string> = {
  json: 'JSON',
  csv: 'CSV',
  markdown: 'MD',
  image: 'PNG',
  video: 'MP4',
  pdf: 'PDF',
  other: 'FILE',
}

const label = computed(() => kindLabel[props.kind] ?? 'FILE')
</script>

<template>
  <span class="artifact-chip" :title="name">
    <span class="artifact-kind">{{ label }}</span>
    <span class="artifact-name">{{ name }}</span>
  </span>
</template>
