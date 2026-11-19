import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunSwimlane from '@/features/runs/RunSwimlane.vue'
import { runFixture } from '@/tests/fixtures/run'

const gateStatus = () => 'pending' as const

function mountSwimlane(overrides: Record<string, unknown> = {}) {
  return mount(RunSwimlane, {
    props: {
      run: runFixture,
      activeStepId: 'step-5',
      runningStepId: 'step-5',
      completedStepIds: new Set(['step-1', 'step-2', 'step-3', 'step-4']),
      showAll: false,
      visibleGateStatus: gateStatus,
      ...overrides,
    },
  })
}

describe('RunSwimlane', () => {
  it('renders eight lanes, ten steps, eight handoffs and one continuation', () => {
    const wrapper = mountSwimlane()

    expect(wrapper.findAll('.lane-label')).toHaveLength(8)
    expect(wrapper.findAll('[data-swimlane-step]')).toHaveLength(10)
    expect(wrapper.findAll('[data-handoff-arrow]')).toHaveLength(8)
    expect(wrapper.findAll('[data-continuation-arrow]')).toHaveLength(1)
  })

  it('marks active and future steps and emits open-step for completed steps', async () => {
    const wrapper = mountSwimlane()

    expect(wrapper.find('[data-step-id="step-5"]').classes()).toContain('run-step-block--active')
    expect(wrapper.find('[data-step-id="step-6"]').classes()).toContain('run-step-block--future')
    expect(wrapper.find('[data-step-id="step-6"]').attributes('disabled')).toBeDefined()

    await wrapper.find('[data-step-id="step-1"]').trigger('click')
    expect(wrapper.emitted('open-step')).toEqual([['step-1']])
  })
})
