<script setup lang="ts">
import { computed } from 'vue'
import type { Run } from '@/api/types'

const props = defineProps<{ run: Run }>()

const emit = defineEmits<{
  (event: 'seek-event', seq: number): void
  (event: 'open-step', stepId: string): void
}>()

const agentNames = computed(
  () => new Map(props.run.agents.map((agent) => [agent.id, agent.name])),
)
const stepNames = computed(
  () => new Map(props.run.steps.map((step) => [step.id, step.name])),
)

function agentName(id: string): string {
  return agentNames.value.get(id) ?? id
}

function stepName(id: string): string {
  return stepNames.value.get(id) ?? id
}
</script>

<template>
  <section class="run-handoff-ledger" data-handoff-ledger aria-label="Agent 交接账本">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">Handoff ledger</p>
        <h2>交接账本 · {{ run.handoffs.length }} 次</h2>
      </div>
      <span class="panel-note">点击定位事件</span>
    </header>
    <ol class="handoff-list">
      <li v-for="(handoff, index) in run.handoffs" :key="handoff.event_seq">
        <button
          class="handoff-row"
          type="button"
          data-handoff-row
          @click="emit('seek-event', handoff.event_seq)"
        >
          <span class="mono handoff-index">{{ index + 1 }}</span>
          <span class="handoff-route">
            {{ agentName(handoff.from_agent_id) }} → {{ agentName(handoff.to_agent_id) }}
          </span>
          <span class="handoff-artifact mono">{{ handoff.artifact }}</span>
          <span class="handoff-steps">
            {{ stepName(handoff.from_step_id) }} → {{ stepName(handoff.to_step_id) }}
          </span>
        </button>
        <button
          class="text-button"
          type="button"
          :aria-label="`查看 ${agentName(handoff.to_agent_id)} 的步骤`"
          @click="emit('open-step', handoff.to_step_id)"
        >
          查看下一步
        </button>
      </li>
      <li v-if="run.handoffs.length === 0" class="empty-row">本次没有 Agent 交接</li>
    </ol>
  </section>
</template>
