<script setup lang="ts">
import type { AgentCard, StatusSummary } from '@/api/types'
import StatusDot from '@/components/ui/StatusDot.vue'
import { useUiStore } from '@/stores/ui'

defineProps<{
  agents: AgentCard[]
  summary: StatusSummary['agents']
}>()

const ui = useUiStore()
</script>

<template>
  <section class="board-card" data-agent-grid>
    <header class="board-card-head">
      <div>
        <p class="board-kicker">Agent 调度</p>
        <h2>{{ agents.length }} 个领域 Agent</h2>
      </div>
      <span class="board-note">运行 {{ summary.running ?? 0 }}</span>
    </header>

    <div class="agent-grid">
      <button
        v-for="agent in agents"
        :key="agent.id"
        class="agent-chip"
        type="button"
        :aria-pressed="ui.selectedAgentId === agent.id"
        :data-agent-id="agent.id"
        @click="
          ui.setAgentFilter(ui.selectedAgentId === agent.id ? null : agent.id)
        "
      >
        <StatusDot :status="agent.status" />
        <span class="agent-name">{{ agent.name }}</span>
        <span class="agent-state">{{ agent.status_label }}</span>
      </button>
    </div>
  </section>
</template>
