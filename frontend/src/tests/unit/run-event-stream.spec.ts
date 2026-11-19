import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunEventStream from '@/features/runs/RunEventStream.vue'
import { runFixture } from '@/tests/fixtures/run'

const approvalIndex = runFixture.events.findIndex(
  (event) => event.kind === 'approval_requested' && event.gate_id === 'budget',
)
const approvalEvent = runFixture.events[approvalIndex]

describe('RunEventStream', () => {
  it('renders only visible events and highlights the active one', () => {
    const wrapper = mount(RunEventStream, {
      props: {
        run: runFixture,
        visibleEvents: runFixture.events.slice(0, 5),
        activeSeq: 5,
        follow: true,
        visibleGateStatus: () => 'pending',
      },
    })

    expect(wrapper.findAll('[data-event-seq]')).toHaveLength(5)
    expect(wrapper.find('[data-event-seq="5"]').classes()).toContain('run-event-row--active')
    expect(wrapper.find('[role="status"]').text()).toContain('第 2 步')
    expect(wrapper.find('[role="status"]').text()).toContain('Agent 交接')
  })

  it('renders a gate card with pending status before the decision', () => {
    const wrapper = mount(RunEventStream, {
      props: {
        run: runFixture,
        visibleEvents: runFixture.events.slice(0, approvalIndex + 1),
        activeSeq: approvalEvent.seq,
        follow: true,
        visibleGateStatus: () => 'pending',
      },
    })

    const card = wrapper.find('[data-gate-card]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-gate-status')).toBe('pending')
    expect(wrapper.find('[role="status"]').text()).toContain('审批待决')
  })
})
