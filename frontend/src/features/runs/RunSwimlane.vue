<script setup lang="ts">
import { computed } from 'vue'
import type { Run, RunGate, RunStep } from '@/api/types'
import RunStepBlock from './RunStepBlock.vue'

const props = defineProps<{
  run: Run
  activeStepId: string | null
  runningStepId: string | null
  completedStepIds: Set<string>
  showAll: boolean
  visibleGateStatus: (gateId: string) => RunGate['status']
}>()

const emit = defineEmits<{ (event: 'open-step', stepId: string): void }>()

const LABEL = 150
const COL = 92
const ROW = 68
const HEADER = 32
const WIDTH = LABEL + 10 * COL
const HEIGHT = HEADER + props.run.agents.length * ROW

const agentRows = computed(
  () => new Map(props.run.agents.map((agent, index) => [agent.id, index])),
)
const agentById = computed(
  () => new Map(props.run.agents.map((agent) => [agent.id, agent])),
)

function stateFor(step: RunStep): 'done' | 'active' | 'future' {
  if (props.showAll) return 'done'
  if (props.completedStepIds.has(step.id)) return 'done'
  if (props.activeStepId === step.id || props.runningStepId === step.id) return 'active'
  return 'future'
}

function stepsForAgent(agentId: string): RunStep[] {
  return props.run.steps.filter((step) => step.agent_id === agentId)
}

function agentFor(agentId: string) {
  return agentById.value.get(agentId)!
}

function gateFor(stepId: string): RunGate | null {
  return props.run.gates.find((gate) => gate.step_id === stepId) ?? null
}

function gateStatus(stepId: string): RunGate['status'] | null {
  const gate = gateFor(stepId)
  return gate ? props.visibleGateStatus(gate.id) : null
}

function xFor(step: RunStep): number {
  return LABEL + (step.index - 1) * COL + COL / 2
}

function yFor(step: RunStep): number {
  const row = agentRows.value.get(step.agent_id) ?? 0
  return HEADER + row * ROW + ROW / 2
}

function handoffPath(fromStepId: string, toStepId: string): string {
  const from = props.run.steps.find((step) => step.id === fromStepId)
  const to = props.run.steps.find((step) => step.id === toStepId)
  if (!from || !to) return ''
  const x1 = xFor(from)
  const y1 = yFor(from)
  const x2 = xFor(to)
  const y2 = yFor(to)
  return `M ${x1} ${y1} C ${x1 + 30} ${y1}, ${x2 - 30} ${y2}, ${x2} ${y2}`
}

function arrowClass(toStepId: string): string {
  if (props.showAll) return 'lane-arrow lane-arrow--done'
  if (props.activeStepId === toStepId) return 'lane-arrow lane-arrow--active'
  if (props.completedStepIds.has(toStepId)) return 'lane-arrow lane-arrow--done'
  return 'lane-arrow lane-arrow--future'
}

const continuations = computed(() => {
  const pairs: Array<{ from: RunStep; to: RunStep }> = []
  for (let index = 0; index < props.run.steps.length - 1; index += 1) {
    const from = props.run.steps[index]
    const to = props.run.steps[index + 1]
    if (from.agent_id !== to.agent_id) continue
    const hasHandoff = props.run.handoffs.some(
      (handoff) => handoff.from_step_id === from.id && handoff.to_step_id === to.id,
    )
    if (!hasHandoff) pairs.push({ from, to })
  }
  return pairs
})

function continuationPath(from: RunStep, to: RunStep): string {
  return `M ${xFor(from)} ${yFor(from)} L ${xFor(to)} ${yFor(to)}`
}
</script>

<template>
  <section class="run-swimlane" data-run-swimlane aria-label="Agent 泳道">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">Relay swimlane</p>
        <h2>{{ run.agents.length }} 个 Agent · {{ run.steps.length }} 步</h2>
      </div>
      <span class="panel-note">点击步骤查看工具与产物</span>
    </header>
    <div class="swimlane-scroll">
      <div
        class="swimlane-grid"
        :style="{
          width: `${WIDTH}px`,
          height: `${HEIGHT}px`,
          gridTemplateColumns: `${LABEL}px repeat(10, ${COL}px)`,
          gridTemplateRows: `${HEADER}px repeat(${run.agents.length}, ${ROW}px)`,
        }"
      >
        <div class="lane-corner" />
        <div
          v-for="step in run.steps"
          :key="`head-${step.id}`"
          class="lane-head mono"
          :style="{ gridColumn: step.index + 1, gridRow: 1 }"
        >
          {{ step.index }}
        </div>
        <template v-for="(agent, rowIndex) in run.agents" :key="agent.id">
          <div class="lane-label" :style="{ gridColumn: 1, gridRow: rowIndex + 2 }">
            <strong>{{ agent.name }}</strong>
            <span>{{ agent.role }}</span>
          </div>
          <RunStepBlock
            v-for="step in stepsForAgent(agent.id)"
            :key="step.id"
            :step="step"
            :agent="agentFor(agent.id)"
            :state="stateFor(step)"
            :gate="gateFor(step.id)"
            :gate-status="gateStatus(step.id)"
            :style="{ gridColumn: step.index + 1, gridRow: rowIndex + 2 }"
            @open="emit('open-step', step.id)"
          />
        </template>
        <svg
          class="lane-arrows"
          :width="WIDTH"
          :height="HEIGHT"
          :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
          aria-hidden="true"
        >
          <defs>
            <marker
              id="run-arrow-head"
              markerWidth="6"
              markerHeight="6"
              refX="5"
              refY="3"
              orient="auto"
            >
              <path d="M0,0 L6,3 L0,6 Z" fill="var(--ink-mute)" />
            </marker>
          </defs>
          <path
            v-for="handoff in run.handoffs"
            :key="handoff.event_seq"
            :d="handoffPath(handoff.from_step_id, handoff.to_step_id)"
            :class="arrowClass(handoff.to_step_id)"
            data-handoff-arrow
            marker-end="url(#run-arrow-head)"
          />
          <path
            v-for="pair in continuations"
            :key="`${pair.from.id}-${pair.to.id}`"
            :d="continuationPath(pair.from, pair.to)"
            class="lane-arrow lane-arrow--continuation"
            data-continuation-arrow
          />
        </svg>
      </div>
    </div>
    <ol class="swimlane-vertical" data-swimlane-mobile>
      <li v-for="step in run.steps" :key="step.id">
        <button
          class="swimlane-mobile-step"
          type="button"
          :disabled="stateFor(step) === 'future'"
          @click="emit('open-step', step.id)"
        >
          <span class="mono">{{ step.index }}</span>
          <strong>{{ agentFor(step.agent_id).name }}</strong>
          <span>{{ step.name }}</span>
          <span>{{ stateFor(step) === 'done' ? '已完成' : stateFor(step) === 'active' ? '进行中' : '待执行' }}</span>
        </button>
      </li>
    </ol>
  </section>
</template>
