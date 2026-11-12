<script setup lang="ts">
import type { StageResult } from '@/api/types'
import ArtifactChip from '@/components/ui/ArtifactChip.vue'

defineProps<{ artifacts: StageResult['artifacts'] }>()
</script>

<template>
  <ul class="artifact-list">
    <li v-for="artifact in artifacts" :key="artifact.uri">
      <ArtifactChip :name="artifact.name" :kind="artifact.kind" />
      <span class="artifact-desc">{{ artifact.description }}</span>
    </li>
  </ul>
</template>
