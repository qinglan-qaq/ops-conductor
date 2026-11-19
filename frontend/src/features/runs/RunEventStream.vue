<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { Run, RunEvent, RunEventKind, RunGate } from '@/api/types'
import RunGateCard from './RunGateCard.vue'

const props = defineProps<{
  run: Run
  visibleEvents: Run['events']
  activeSeq: number | null
  follow: boolean
  visibleGateStatus: (gateId: string) => RunGate['status']
}>()

const listRef = ref<HTMLElement | null>(null)

const labels: Record<RunEventKind, string> = {
  run_started: '开始',
  agent_started: 'Agent',
  tool_called: '工具',
  step_completed: '完成',
  handoff: '交接',
  approval_requested: '待批',
  approval_decided: '裁决',
  verification_passed: '验证',
  compensation_triggered: '补偿',
  rpa_executed: 'RPA',
  reconciliation_found: '对账',
  report_generated: '报告',
  run_completed: '完成',
}

function stepFor(event: RunEvent) {
  return props.run.steps.find((step) => step.id === event.step_id) ?? null
}

function agentName(event: RunEvent): string {
  return props.run.agents.find((agent) => agent.id === event.agent_id)?.name ?? ''
}

function gateFor(event: RunEvent): RunGate | null {
  if (!event.gate_id) return null
  return props.run.gates.find((gate) => gate.id === event.gate_id) ?? null
}

function showDivider(index: number, event: RunEvent): boolean {
  if (!event.step_id) return false
  const previous = props.visibleEvents[index - 1]
  return !previous || previous.step_id !== event.step_id
}

const activeEvent = computed(
  () => props.visibleEvents.find((event) => event.seq === props.activeSeq) ?? null,
)

const activeSummary = computed(() => {
  const event = activeEvent.value
  if (!event) return '等待运行开始'
  const step = stepFor(event)
  const agent = agentName(event)
  return `第 ${step?.index ?? '-'} 步 · ${agent || '系统'} · ${event.title}`
})

function scrollToActive(seq: number): void {
  void nextTick(() => {
    const element = listRef.value?.querySelector<HTMLElement>(
      `[data-event-seq="${seq}"]`,
    )
    element?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  })
}

watch(
  () => props.activeSeq,
  (seq) => {
    if (seq !== null && props.follow) scrollToActive(seq)
  },
)
</script>

<template>
  <section class="run-event-stream" data-run-event-stream aria-label="运行事件流">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">Event stream</p>
        <h2>{{ visibleEvents.length }} / {{ run.events.length }} 事件</h2>
      </div>
      <span class="panel-note">#seq 为回放顺序</span>
    </header>
    <p class="run-sr-only" role="status" aria-live="polite">{{ activeSummary }}</p>
    <ol ref="listRef" class="run-event-list">
      <template v-for="(event, index) in visibleEvents" :key="event.seq">
        <li v-if="showDivider(index, event)" class="run-event-divider">
          第 {{ stepFor(event)?.index }} 步 · {{ stepFor(event)?.name }}
        </li>
        <li
          class="run-event-row"
          :class="{ 'run-event-row--active': event.seq === activeSeq }"
          :data-event-seq="event.seq"
        >
          <span class="run-event-kind">{{ labels[event.kind] }}</span>
          <time class="run-event-time mono">{{ event.at }}</time>
          <span class="run-event-seq mono">#{{ event.seq }}</span>
          <strong class="run-event-title">{{ event.title }}</strong>
          <p class="run-event-detail">{{ event.detail }}</p>
          <RunGateCard
            v-if="gateFor(event)"
            :gate="gateFor(event)!"
            :status="visibleGateStatus(gateFor(event)!.id)"
          />
        </li>
      </template>
      <li v-if="visibleEvents.length === 0" class="empty-row">等待运行开始…</li>
    </ol>
  </section>
</template>
