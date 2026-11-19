<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { Run } from '@/api/types'
import RunHeader from './RunHeader.vue'
import RunChainStrip from './RunChainStrip.vue'
import RunSwimlane from './RunSwimlane.vue'
import RunEventStream from './RunEventStream.vue'
import RunHandoffLedger from './RunHandoffLedger.vue'
import RunGovernanceStrip from './RunGovernanceStrip.vue'
import RunControls from './RunControls.vue'
import RunSummary from './RunSummary.vue'
import RunStepDrawer from './RunStepDrawer.vue'
import { useRunPlayer } from './useRunPlayer'

const props = defineProps<{ run: Run }>()

function firstQuery(value: unknown): unknown {
  return Array.isArray(value) ? value[0] : value
}

function parseSpeed(value: unknown): 1 | 2 | 4 {
  const parsed = Number(firstQuery(value))
  return parsed === 2 || parsed === 4 ? parsed : 1
}

function parseAutoplay(value: unknown): boolean {
  const raw = firstQuery(value)
  return !(raw === '0' || raw === 0 || raw === false)
}

const route = useRoute()
const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches
const player = useRunPlayer(props.run, {
  speed: parseSpeed(route.query.speed),
  autoplay: parseAutoplay(route.query.autoplay),
  reducedMotion,
})

const {
  status,
  cursor,
  speed,
  follow,
  showAll,
  visibleEvents,
  activeEvent,
  activeStepId,
  runningStepId,
  completedStepIds,
  progress,
  visibleGateStatus,
} = player

const activeSeq = computed(() => activeEvent.value?.seq ?? null)
const visibleEventSeqs = computed(
  () => new Set(visibleEvents.value.map((event) => event.seq)),
)
const selectedStepId = ref<string | null>(null)

const selectedStep = computed(
  () => props.run.steps.find((step) => step.id === selectedStepId.value) ?? null,
)
const selectedIndex = computed(() =>
  selectedStep.value
    ? props.run.steps.findIndex((step) => step.id === selectedStep.value!.id)
    : -1,
)
const selectedAgent = computed(
  () =>
    props.run.agents.find((agent) => agent.id === selectedStep.value?.agent_id) ??
    null,
)
const selectedArtifact = computed(() => {
  const step = selectedStep.value
  if (!step?.artifact) return null
  return (
    props.run.artifacts.find(
      (artifact) => artifact.step_id === step.id && artifact.name === step.artifact,
    ) ?? null
  )
})
const selectedGate = computed(
  () =>
    props.run.gates.find((gate) => gate.step_id === selectedStep.value?.id) ?? null,
)
const selectedGateStatus = computed(() =>
  selectedGate.value ? visibleGateStatus(selectedGate.value.id) : null,
)
const previousStep = computed(() =>
  selectedIndex.value > 0 ? props.run.steps[selectedIndex.value - 1] : null,
)
const nextStep = computed(() =>
  selectedIndex.value >= 0 && selectedIndex.value < props.run.steps.length - 1
    ? props.run.steps[selectedIndex.value + 1]
    : null,
)

function openStep(stepId: string): void {
  const step = props.run.steps.find((item) => item.id === stepId)
  if (!step) return
  const selectable =
    showAll.value ||
    completedStepIds.value.has(stepId) ||
    activeStepId.value === stepId ||
    runningStepId.value === stepId
  if (!selectable) return
  selectedStepId.value = stepId
  player.seekToStep(stepId)
}

function seekStep(stepId: string): void {
  player.seekToStep(stepId)
  if (selectedStepId.value !== null) selectedStepId.value = stepId
}

function seekEvent(seq: number): void {
  player.seekToEvent(seq)
}

function closeDrawer(): void {
  selectedStepId.value = null
}

function toggleFollow(): void {
  follow.value = !follow.value
}

function onKeydown(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
  if (selectedStepId.value) return
  if (event.key === ' ') {
    event.preventDefault()
    player.toggle()
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    player.stepForward()
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    player.stepBack()
  } else if (event.key.toLowerCase() === 'r') {
    player.replay()
  } else if (event.key === '1' || event.key === '2' || event.key === '4') {
    player.setSpeed(Number(event.key) as 1 | 2 | 4)
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  player.dispose()
})
</script>

<template>
  <div class="run-body" data-run-body>
    <RunHeader :run="run" />
    <RunChainStrip
      :run="run"
      :active-step-id="activeStepId"
      :running-step-id="runningStepId"
      :completed-step-ids="completedStepIds"
      :show-all="showAll"
      :visible-gate-status="visibleGateStatus"
      @seek-step="seekStep"
      @seek-event="seekEvent"
    />
    <div class="run-layout">
      <RunSwimlane
        :run="run"
        :active-step-id="activeStepId"
        :running-step-id="runningStepId"
        :completed-step-ids="completedStepIds"
        :show-all="showAll"
        :visible-gate-status="visibleGateStatus"
        @open-step="openStep"
      />
      <RunEventStream
        :run="run"
        :visible-events="visibleEvents"
        :active-seq="activeSeq"
        :follow="follow"
        :visible-gate-status="visibleGateStatus"
      />
    </div>
    <RunHandoffLedger :run="run" @seek-event="seekEvent" @open-step="openStep" />
    <RunGovernanceStrip
      :run="run"
      :visible-event-seqs="visibleEventSeqs"
      :active-seq="activeSeq"
      @seek-event="seekEvent"
    />
    <RunControls
      :status="status"
      :speed="speed"
      :progress="progress"
      :cursor="cursor"
      :total="run.events.length"
      :show-all="showAll"
      :follow="follow"
      @toggle="player.toggle"
      @prev="player.stepBack"
      @next="player.stepForward"
      @replay="player.replay"
      @speed="player.setSpeed"
      @toggle-show-all="player.toggleShowAll"
      @toggle-follow="toggleFollow"
    />
    <RunSummary v-if="status === 'finished' || showAll" :run="run" />
    <RunStepDrawer
      v-if="selectedStep && selectedAgent"
      :step="selectedStep"
      :agent="selectedAgent"
      :artifact="selectedArtifact"
      :gate="selectedGate"
      :gate-status="selectedGateStatus"
      :previous="previousStep"
      :next="nextStep"
      @close="closeDrawer"
      @seek-step="seekStep"
    />
  </div>
</template>
