import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunChainStrip from '@/features/runs/RunChainStrip.vue'
import { runFixture } from '@/tests/fixtures/run'

const gateStatus = () => 'pending' as const

describe('RunChainStrip', () => {
  it('renders ten nodes, eight handoffs and one continuation', () => {
    const wrapper = mount(RunChainStrip, {
      props: {
        run: runFixture,
        activeStepId: 'step-5',
        runningStepId: null,
        completedStepIds: new Set(['step-1', 'step-2', 'step-3', 'step-4']),
        showAll: false,
        visibleGateStatus: gateStatus,
      },
    })

    expect(wrapper.findAll('[data-chain-node]')).toHaveLength(10)
    expect(wrapper.findAll('[data-handoff-link]')).toHaveLength(8)
    expect(wrapper.findAll('[data-continuation-link]')).toHaveLength(1)
    expect(wrapper.find('[data-gate-id="budget"]').text()).toContain('待批')
  })

  it('emits seek-step when a node is clicked', async () => {
    const wrapper = mount(RunChainStrip, {
      props: {
        run: runFixture,
        activeStepId: null,
        runningStepId: null,
        completedStepIds: new Set<string>(),
        showAll: false,
        visibleGateStatus: gateStatus,
      },
    })

    await wrapper.findAll('[data-chain-node]')[4].trigger('click')

    expect(wrapper.emitted('seek-step')).toEqual([['step-5']])
  })
})
