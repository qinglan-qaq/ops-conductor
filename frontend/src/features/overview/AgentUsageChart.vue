<script setup lang="ts">
import { computed } from 'vue'
import type { AgentUsage } from '@/api/types'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ usage: AgentUsage[] }>()

const ui = useUiStore()
const maxRuns = computed(() =>
  Math.max(...props.usage.map((item) => item.runs), 1),
)

function focusAgent(agentId: string): void {
  ui.setAgentFilter(agentId)
  const target = document.getElementById('agents')
  if (target && typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({ block: 'start' })
  }
}
</script>

<template>
  <section class="panel chart-panel" data-agent-usage-chart>
    <header class="chart-head">
      <div>
        <p class="panel-kicker">Agent 使用量</p>
        <h2>调用与成功率</h2>
      </div>
      <span class="chart-note">点击筛选 Agent</span>
    </header>

    <div class="usage-chart">
      <button
        v-for="item in usage"
        :key="item.agent_id"
        class="usage-row"
        type="button"
        :aria-pressed="ui.selectedAgentId === item.agent_id"
        :aria-label="`${item.name}：${item.runs} 次调用，成功率 ${item.success_rate}%`"
        :data-agent-usage="item.agent_id"
        @click="focusAgent(item.agent_id)"
      >
        <span class="usage-name">{{ item.name }}</span>
        <span class="usage-track" aria-hidden="true">
          <span
            class="usage-fill"
            :style="{ width: `${(item.runs / maxRuns) * 100}%` }"
          />
        </span>
        <span class="usage-stat">
          <strong class="mono">{{ item.runs }}</strong>
          <small class="mono">{{ item.success_rate }}%</small>
        </span>
      </button>
    </div>
    <p class="chart-footnote">
      平均耗时 {{ Math.round((usage[0]?.avg_duration_ms ?? 0) / 1000) }}s 起 ·
      Mock 演示数据
    </p>
  </section>
</template>
