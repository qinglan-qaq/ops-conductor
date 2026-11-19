<script setup lang="ts">
import { computed } from 'vue'
import type { RunGate } from '@/api/types'
import RiskBadge from '@/components/ui/RiskBadge.vue'

const props = defineProps<{
  gate: RunGate
  status: RunGate['status']
}>()

const statusLabel = computed(() =>
  props.status === 'approved' ? '已准' : props.status === 'rejected' ? '已驳' : '待批',
)
const recommendedLabel = computed(() =>
  props.gate.recommended === 'approve' ? '建议准' : props.gate.recommended === 'reject' ? '建议驳' : '无建议',
)
</script>

<template>
  <article class="run-gate-card" data-gate-card :data-gate-status="status">
    <header>
      <RiskBadge :risk="gate.risk" />
      <strong>{{ gate.title }}</strong>
      <span class="run-gate-status">{{ statusLabel }}</span>
    </header>
    <p>{{ gate.owner }} · {{ gate.impact }}</p>
    <p class="run-gate-recommendation">
      {{ recommendedLabel }}
      <span v-if="gate.actor"> · 剧本裁决：{{ gate.actor }}</span>
    </p>
  </article>
</template>
