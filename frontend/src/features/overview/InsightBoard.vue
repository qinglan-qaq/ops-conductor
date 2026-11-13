<script setup lang="ts">
import type { Analytics } from '@/api/types'
import SalesTrendChart from './SalesTrendChart.vue'
import AgentUsageChart from './AgentUsageChart.vue'
import ResultDeliveryChart from './ResultDeliveryChart.vue'

defineProps<{ analytics: Analytics }>()
</script>

<template>
  <section class="insight-board" data-insight-board aria-labelledby="insight-title">
    <header class="insight-head">
      <div>
        <p class="page-kicker">Charts · 经营可视化</p>
        <h2 id="insight-title">销售 · Agent · 结果</h2>
      </div>
      <span class="mock-pill">MOCK · 近 7 日</span>
    </header>

    <div class="insight-grid">
      <div class="insight-stack">
        <SalesTrendChart :sales="analytics.sales" />
        <ResultDeliveryChart :results="analytics.results" />
      </div>
      <AgentUsageChart :usage="analytics.agent_usage" />
    </div>
  </section>
</template>
