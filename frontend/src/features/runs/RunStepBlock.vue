<script setup lang="ts">
import { computed } from 'vue'
import type { RunAgent, RunGate, RunStep } from '@/api/types'

const props = defineProps<{
  step: RunStep
  agent: RunAgent
  state: 'done' | 'active' | 'future'
  gate: RunGate | null
  gateStatus: RunGate['status'] | null
}>()

const emit = defineEmits<{ (event: 'open'): void }>()

const stateLabel = computed(() =>
  props.state === 'done' ? '已完成' : props.state === 'active' ? '进行中' : '待执行',
)
const gateLabel = computed(() =>
  props.gateStatus === 'approved'
    ? '准'
    : props.gateStatus === 'rejected'
      ? '驳'
      : props.gateStatus === 'pending'
        ? '待批'
        : '',
)
</script>

<template>
  <button
    class="run-step-block"
    :class="`run-step-block--${state}`"
    type="button"
    data-swimlane-step
    :data-step-id="step.id"
    :disabled="state === 'future'"
    :title="`${agent.name} · ${step.name}`"
    @click="emit('open')"
  >
    <span class="step-block-name">{{ step.name }}</span>
    <span class="step-block-state">{{ stateLabel }}</span>
    <span v-if="step.artifact" class="step-block-artifact mono">{{ step.artifact }}</span>
    <span v-if="gate" class="step-block-gate" :class="`step-block-gate--${gateStatus}`">
      {{ gate.risk }} · {{ gateLabel }}
    </span>
  </button>
</template>
