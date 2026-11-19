import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type { Run, RunEventKind, RunGate } from '@/api/types'

export type PlayerStatus = 'idle' | 'playing' | 'paused' | 'finished'

export interface RunPlayerOptions {
  speed?: 1 | 2 | 4
  autoplay?: boolean
  reducedMotion?: boolean
}

const EVENT_DURATION: Record<RunEventKind, number> = {
  run_started: 600,
  agent_started: 500,
  tool_called: 450,
  step_completed: 550,
  handoff: 450,
  approval_requested: 900,
  approval_decided: 900,
  verification_passed: 800,
  compensation_triggered: 900,
  rpa_executed: 700,
  reconciliation_found: 700,
  report_generated: 600,
  run_completed: 700,
}

export interface RunPlayer {
  status: Ref<PlayerStatus>
  cursor: Ref<number>
  speed: Ref<1 | 2 | 4>
  follow: Ref<boolean>
  showAll: Ref<boolean>
  visibleEvents: ComputedRef<Run['events']>
  activeEvent: ComputedRef<Run['events'][number] | null>
  activeStepId: ComputedRef<string | null>
  activeAgentId: ComputedRef<string | null>
  completedStepIds: ComputedRef<Set<string>>
  runningStepId: ComputedRef<string | null>
  progress: ComputedRef<number>
  totalDurationMs: ComputedRef<number>
  play: () => void
  pause: () => void
  toggle: () => void
  stepForward: () => void
  stepBack: () => void
  seek: (index: number) => void
  seekToEvent: (seq: number) => void
  seekToStep: (stepId: string) => void
  replay: () => void
  setSpeed: (speed: 1 | 2 | 4) => void
  toggleShowAll: () => void
  visibleGateStatus: (gateId: string) => RunGate['status']
  dispose: () => void
}

/** 导演模式播放器：Run 是事实，cursor 只决定揭示到哪一步。 */
export function useRunPlayer(run: Run, options: RunPlayerOptions = {}): RunPlayer {
  const total = run.events.length
  const reducedMotion = options.reducedMotion ?? false
  const status = ref<PlayerStatus>(reducedMotion ? 'finished' : 'idle')
  const cursor = ref(reducedMotion ? total : 0)
  const speed = ref<1 | 2 | 4>(options.speed ?? 1)
  const follow = ref(true)
  const showAll = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  const clearTimer = (): void => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const visibleEvents = computed(() =>
    showAll.value ? run.events : run.events.slice(0, cursor.value),
  )

  const activeEvent = computed(() => {
    if (showAll.value) return null
    return visibleEvents.value.at(-1) ?? null
  })

  const activeStepId = computed(() => activeEvent.value?.step_id ?? null)
  const activeAgentId = computed(() => activeEvent.value?.agent_id ?? null)

  const completedStepIds = computed(() => {
    const ids = new Set<string>()
    for (const event of visibleEvents.value) {
      if (event.kind === 'step_completed' && event.step_id) {
        ids.add(event.step_id)
      }
    }
    return ids
  })

  const runningStepId = computed(() => {
    const running = new Set<string>()
    for (const event of visibleEvents.value) {
      if (event.kind === 'agent_started' && event.step_id) {
        running.add(event.step_id)
      } else if (event.kind === 'step_completed' && event.step_id) {
        running.delete(event.step_id)
      }
    }
    return [...running].at(-1) ?? null
  })

  const progress = computed(() =>
    total === 0 ? 0 : showAll.value ? 1 : cursor.value / total,
  )

  const totalDurationMs = computed(() =>
    run.events.reduce((sum, event) => sum + EVENT_DURATION[event.kind], 0),
  )

  const visibleGateStatus = (gateId: string): RunGate['status'] => {
    const gate = run.gates.find((item) => item.id === gateId)
    if (!gate) return 'pending'
    if (showAll.value) return gate.status
    const decided = visibleEvents.value.some(
      (event) => event.kind === 'approval_decided' && event.gate_id === gateId,
    )
    return decided ? gate.status : 'pending'
  }

  const scheduleNext = (): void => {
    clearTimer()
    if (status.value !== 'playing') return
    if (cursor.value >= total) {
      status.value = 'finished'
      return
    }
    const event = run.events[cursor.value]
    const duration = EVENT_DURATION[event.kind] / speed.value
    timer = setTimeout(() => {
      timer = null
      if (status.value !== 'playing') return
      cursor.value += 1
      if (cursor.value >= total) {
        status.value = 'finished'
      } else {
        scheduleNext()
      }
    }, duration)
  }

  const play = (): void => {
    if (status.value === 'playing') return
    if (total === 0) {
      status.value = 'finished'
      return
    }
    if (cursor.value >= total) cursor.value = 0
    showAll.value = false
    status.value = 'playing'
    scheduleNext()
  }

  const pause = (): void => {
    clearTimer()
    if (status.value === 'playing') status.value = 'paused'
  }

  const replay = (): void => {
    clearTimer()
    showAll.value = false
    cursor.value = 0
    status.value = 'playing'
    scheduleNext()
  }

  const toggle = (): void => {
    if (status.value === 'playing') pause()
    else if (status.value === 'finished') replay()
    else play()
  }

  const stepForward = (): void => {
    clearTimer()
    if (cursor.value < total) cursor.value += 1
    status.value = cursor.value >= total ? 'finished' : 'paused'
  }

  const stepBack = (): void => {
    clearTimer()
    if (cursor.value > 0) cursor.value -= 1
    status.value = 'paused'
  }

  const seek = (index: number): void => {
    clearTimer()
    cursor.value = Math.min(Math.max(index, 0), total)
    status.value = cursor.value >= total ? 'finished' : 'paused'
  }

  const seekToEvent = (seq: number): void => {
    showAll.value = false
    follow.value = true
    seek(Math.min(Math.max(seq, 0), total))
  }

  const seekToStep = (stepId: string): void => {
    const index = run.events.findIndex(
      (event) => event.kind === 'agent_started' && event.step_id === stepId,
    )
    if (index < 0) return
    showAll.value = false
    follow.value = true
    seek(index + 1)
  }

  const setSpeed = (next: 1 | 2 | 4): void => {
    speed.value = next
    if (status.value === 'playing') scheduleNext()
  }

  const toggleShowAll = (): void => {
    if (!showAll.value) {
      pause()
      showAll.value = true
      return
    }
    showAll.value = false
    cursor.value = 0
    status.value = 'paused'
    clearTimer()
  }

  const dispose = (): void => {
    clearTimer()
  }

  if (!reducedMotion && (options.autoplay ?? true)) {
    play()
  }

  return {
    status,
    cursor,
    speed,
    follow,
    showAll,
    visibleEvents,
    activeEvent,
    activeStepId,
    activeAgentId,
    completedStepIds,
    runningStepId,
    progress,
    totalDurationMs,
    play,
    pause,
    toggle,
    stepForward,
    stepBack,
    seek,
    seekToEvent,
    seekToStep,
    replay,
    setSpeed,
    toggleShowAll,
    visibleGateStatus,
    dispose,
  }
}
