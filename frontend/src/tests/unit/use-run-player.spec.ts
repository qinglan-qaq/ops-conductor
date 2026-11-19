import { afterEach, describe, expect, it, vi } from 'vitest'
import { useRunPlayer } from '@/features/runs/useRunPlayer'
import { runFixture } from '@/tests/fixtures/run'

function eventIndex(kind: string, gateId?: string) {
  return runFixture.events.findIndex(
    (event) => event.kind === kind && (!gateId || event.gate_id === gateId),
  )
}

describe('useRunPlayer', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts idle and reveals nothing before play', () => {
    const player = useRunPlayer(runFixture, { autoplay: false })

    expect(player.status.value).toBe('idle')
    expect(player.cursor.value).toBe(0)
    expect(player.visibleEvents.value).toHaveLength(0)
    player.dispose()
  })

  it('advances one event per frame and stops when paused', () => {
    vi.useFakeTimers()
    const player = useRunPlayer(runFixture, { autoplay: false })

    player.play()
    expect(player.status.value).toBe('playing')
    vi.advanceTimersByTime(600)
    expect(player.cursor.value).toBe(1)
    vi.advanceTimersByTime(500)
    expect(player.cursor.value).toBe(2)

    player.pause()
    vi.advanceTimersByTime(10_000)
    expect(player.cursor.value).toBe(2)
    player.dispose()
  })

  it('supports single-step forward and backward', () => {
    const player = useRunPlayer(runFixture, { autoplay: false })

    player.stepForward()
    player.stepForward()
    expect(player.cursor.value).toBe(2)
    expect(player.status.value).toBe('paused')

    player.stepBack()
    expect(player.cursor.value).toBe(1)
    player.dispose()
  })

  it('seeks to a step and pauses', () => {
    const player = useRunPlayer(runFixture, { autoplay: false })
    const index = runFixture.events.findIndex(
      (event) => event.kind === 'agent_started' && event.step_id === 'step-5',
    )

    player.seekToStep('step-5')

    expect(player.cursor.value).toBe(index + 1)
    expect(player.status.value).toBe('paused')
    expect(player.activeStepId.value).toBe('step-5')
    player.dispose()
  })

  it('seeks to an event and keeps gate pending until its decision', () => {
    const player = useRunPlayer(runFixture, { autoplay: false })
    const requested = eventIndex('approval_requested', 'budget') + 1
    const decided = eventIndex('approval_decided', 'budget') + 1

    player.seekToEvent(requested)
    expect(player.visibleGateStatus('budget')).toBe('pending')

    player.seekToEvent(decided)
    expect(player.visibleGateStatus('budget')).toBe('approved')
    player.dispose()
  })

  it('honours playback speed', () => {
    vi.useFakeTimers()
    const player = useRunPlayer(runFixture, { autoplay: false, speed: 4 })

    player.play()
    vi.advanceTimersByTime(150)
    expect(player.cursor.value).toBe(1)
    player.dispose()
  })

  it('replays from the beginning', () => {
    vi.useFakeTimers()
    const player = useRunPlayer(runFixture, { autoplay: false })

    player.stepForward()
    player.stepForward()
    player.replay()

    expect(player.cursor.value).toBe(0)
    expect(player.status.value).toBe('playing')
    vi.advanceTimersByTime(600)
    expect(player.cursor.value).toBe(1)
    player.dispose()
  })

  it('shows the complete run and returns to replay', () => {
    const player = useRunPlayer(runFixture, { autoplay: false })

    player.toggleShowAll()

    expect(player.showAll.value).toBe(true)
    expect(player.visibleEvents.value).toHaveLength(51)
    expect(player.visibleGateStatus('budget')).toBe('approved')

    player.toggleShowAll()
    expect(player.showAll.value).toBe(false)
    expect(player.cursor.value).toBe(0)
    expect(player.status.value).toBe('paused')
    player.dispose()
  })

  it('starts finished when reduced motion is requested', () => {
    const player = useRunPlayer(runFixture, {
      autoplay: true,
      reducedMotion: true,
    })

    expect(player.status.value).toBe('finished')
    expect(player.cursor.value).toBe(51)
    expect(player.visibleEvents.value).toHaveLength(51)
    player.dispose()
  })

  it('dispose clears pending timers', () => {
    vi.useFakeTimers()
    const player = useRunPlayer(runFixture, { autoplay: false })

    player.play()
    player.dispose()
    vi.advanceTimersByTime(10_000)

    expect(player.cursor.value).toBe(0)
  })
})
