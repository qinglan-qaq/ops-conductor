<script setup lang="ts">
import type { Run } from '@/api/types'

defineProps<{ run: Run }>()
</script>

<template>
  <section class="run-summary" data-run-summary aria-label="运行摘要">
    <div>
      <p class="panel-kicker">Run complete</p>
      <h2>{{ run.summary }}</h2>
      <p class="run-summary-note">
        {{ run.metrics.step_count }} 步 · {{ run.metrics.agent_count }} Agent ·
        {{ run.metrics.handoff_count }} 次交接 · {{ run.metrics.gate_count }} 个门禁 ·
        {{ run.metrics.compensation_count }} 次补偿 · {{ run.metrics.reconciliation_count }} 笔对账差异
      </p>
    </div>
    <ul class="run-summary-chips">
      <li>Verifier {{ run.verification.passed ? '通过' : '未通过' }}</li>
      <li v-for="veto in run.verification.vetoed" :key="veto">{{ veto }}</li>
    </ul>
  </section>
</template>
