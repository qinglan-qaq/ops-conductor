<script setup lang="ts">
import { computed } from 'vue'
import type { Run, RunGate, RunStep } from '@/api/types'

const props = defineProps<{
  run: Run
  activeStepId: string | null
  runningStepId: string | null
  completedStepIds: Set<string>
  showAll: boolean
  visibleGateStatus: (gateId: string) => RunGate['status']
}>()

const emit = defineEmits<{
  (event: 'seek-step', stepId: string): void
  (event: 'seek-event', seq: number): void
}>()

const agentNames = computed(
  () =>
    new Map(
      props.run.agents.map((agent) => [
        agent.id,
        agent.name.replace(' Agent', ''),
      ]),
    ),
)
const handoffByFrom = computed(
  () => new Map(props.run.handoffs.map((handoff) => [handoff.from_step_id, handoff])),
)

function gateFor(stepId: string): RunGate | undefined {
  return props.run.gates.find((gate) => gate.step_id === stepId)
}

function gateLabel(gate: RunGate): string {
  const status = props.visibleGateStatus(gate.id)
  const label = status === 'approved' ? '准' : status === 'rejected' ? '驳' : '待批'
  return `${gate.risk} · ${label}`
}

function nodeClass(step: RunStep): string {
  if (props.showAll) return 'chain-node--done'
  if (props.activeStepId === step.id || props.runningStepId === step.id) {
    return 'chain-node--active'
  }
  if (props.completedStepIds.has(step.id)) return 'chain-node--done'
  return 'chain-node--future'
}

function linkClass(to: RunStep): string {
  if (props.showAll) return 'chain-link--done'
  if (props.activeStepId === to.id) return 'chain-link--active'
  if (props.completedStepIds.has(to.id)) return 'chain-link--done'
  return 'chain-link--future'
}

function linkTitle(from: RunStep, to: RunStep): string {
  const handoff = handoffByFrom.value.get(from.id)
  if (!handoff) return `${agentNames.value.get(from.agent_id) ?? from.agent_id} 继续 · ${to.name}`
  return `${agentNames.value.get(handoff.from_agent_id)} → ${agentNames.value.get(handoff.to_agent_id)} · ${handoff.artifact}`
}

function onLink(from: RunStep, to: RunStep): void {
  const handoff = handoffByFrom.value.get(from.id)
  if (handoff) emit('seek-event', handoff.event_seq)
  else emit('seek-step', to.id)
}
</script>

<template>
  <section class="run-chain-strip" data-run-chain-strip aria-label="执行链总览">
    <div class="chain-strip-head">
      <p class="panel-kicker">Execution chain</p>
      <span>10 步 · {{ run.handoffs.length }} 次交接</span>
    </div>
    <div class="chain-strip-track">
      <div v-for="(step, index) in run.steps" :key="step.id" class="chain-item">
        <button
          class="chain-node"
          :class="nodeClass(step)"
          type="button"
          data-chain-node
          :data-step-id="step.id"
          @click="emit('seek-step', step.id)"
        >
          <span class="chain-index mono">{{ step.index }}</span>
          <span class="chain-agent">{{ agentNames.get(step.agent_id) ?? step.agent_id }}</span>
          <span
            v-if="gateFor(step.id)"
            class="chain-gate"
            :class="`chain-gate--${visibleGateStatus(gateFor(step.id)!.id)}`"
            :data-gate-id="gateFor(step.id)!.id"
          >
            {{ gateLabel(gateFor(step.id)!) }}
          </span>
        </button>
        <button
          v-if="index < run.steps.length - 1"
          class="chain-link"
          :class="linkClass(run.steps[index + 1])"
          type="button"
          :data-handoff-link="handoffByFrom.get(step.id) ? '' : undefined"
          :data-continuation-link="handoffByFrom.get(step.id) ? undefined : ''"
          :title="linkTitle(step, run.steps[index + 1])"
          :aria-label="linkTitle(step, run.steps[index + 1])"
          @click="onLink(step, run.steps[index + 1])"
        >
          <span v-if="handoffByFrom.get(step.id)" class="chain-link-label">
            {{ handoffByFrom.get(step.id)!.artifact }}
          </span>
          <span v-else class="chain-link-label">延续</span>
        </button>
      </div>
    </div>
  </section>
</template>
