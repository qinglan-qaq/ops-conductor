<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { StageDetail, StageStatus } from '@/api/types'
import StatusDot from '@/components/ui/StatusDot.vue'
import RiskBadge from '@/components/ui/RiskBadge.vue'

const props = defineProps<{
  stageId: string
  steps: StageDetail['steps']
  stageStatus: StageStatus
  activeStepId: string | null
  owner: string
  risk: string
}>()

const router = useRouter()

function stepHref(stepId: string): string {
  return router.resolve({
    name: 'stage',
    params: { stageId: props.stageId },
    query: { step: stepId },
  }).href
}

function openStep(stepId: string): void {
  void router.push({
    name: 'stage',
    params: { stageId: props.stageId },
    query: { step: stepId },
  })
}

function stepStatus(index: number, stepId: string): StageStatus {
  if (props.activeStepId === stepId) return 'running'
  if (props.stageStatus === 'done') return 'done'
  if (props.stageStatus === 'alert') {
    if (index === 0) return 'done'
    if (index === 1) return 'alert'
  }
  if (props.stageStatus === 'running') {
    if (index === 0) return 'done'
    if (index === 1) return 'running'
  }
  return index === 0 ? 'done' : 'waiting'
}
</script>

<template>
  <section class="stage-column panel" aria-label="阶段流程">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">流程</p>
        <h2>{{ steps.length }} 个子流程</h2>
      </div>
      <RiskBadge :risk="risk" />
    </header>

    <ol class="stage-flow">
      <li v-for="(step, index) in steps" :key="step.id">
        <a
          class="flow-step"
          :class="{ 'is-active': activeStepId === step.id }"
          :href="stepHref(step.id)"
          :aria-current="activeStepId === step.id ? 'page' : undefined"
          @click.prevent="openStep(step.id)"
        >
          <span class="flow-index mono">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="flow-name">{{ step.name }}</span>
          <StatusDot :status="stepStatus(index, step.id)" />
        </a>
      </li>
    </ol>

    <footer class="stage-flow-foot">
      <span>主责：{{ owner }}</span>
      <span class="mono">{{ activeStepId ?? '未选子流程' }}</span>
    </footer>
  </section>
</template>
