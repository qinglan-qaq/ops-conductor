<script setup lang="ts">
import { computed } from 'vue'
import type { Run } from '@/api/types'

const props = defineProps<{ run: Run }>()

const durationLabel = computed(() =>
  props.run.metrics.duration_ms < 1 ? '<1ms' : `${props.run.metrics.duration_ms}ms`,
)
const statusLabel = computed(() =>
  props.run.status === 'succeeded' ? '已完成' : props.run.status,
)
</script>

<template>
  <header class="run-header" data-run-header>
    <div class="run-header-main">
      <RouterLink class="text-link run-back" to="/dispatch">← 返回今日态势</RouterLink>
      <p class="page-kicker">Agent Run · {{ run.mode.toUpperCase() }}</p>
      <h1>{{ run.goal.instruction }}</h1>
      <p class="page-lede">
        {{ run.goal.store }} · {{ run.goal.market }} ·
        <span class="mono">{{ run.id }}</span>
      </p>
      <p class="run-readonly" role="note">
        DEMO · 只读回放 · 审批状态未改变
      </p>
    </div>
    <div class="run-header-side">
      <span class="run-status" :class="`run-status--${run.status}`">{{ statusLabel }}</span>
      <div class="run-header-metrics">
        <div><strong>{{ run.metrics.step_count }}</strong><span>步骤</span></div>
        <div><strong>{{ run.metrics.agent_count }}</strong><span>Agent</span></div>
        <div><strong>{{ run.metrics.handoff_count }}</strong><span>交接</span></div>
        <div><strong>{{ run.metrics.gate_count }}</strong><span>门禁</span></div>
        <div><strong>{{ run.metrics.approved_gates }}/{{ run.metrics.rejected_gates }}</strong><span>准/驳</span></div>
        <div><strong>{{ run.metrics.artifact_count }}</strong><span>产物</span></div>
        <div><strong>{{ run.metrics.compensation_count }}</strong><span>补偿</span></div>
        <div><strong>{{ run.metrics.reconciliation_count }}</strong><span>对账</span></div>
        <div><strong class="mono">{{ durationLabel }}</strong><span>实测耗时</span></div>
      </div>
      <p class="run-verification">
        Verifier：{{ run.verification.passed ? '通过' : '未通过' }} ·
        {{ run.verification.vetoed.length }} 项否决
      </p>
    </div>
  </header>
</template>
