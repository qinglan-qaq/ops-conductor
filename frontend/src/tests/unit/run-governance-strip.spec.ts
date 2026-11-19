import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunGovernanceStrip from '@/features/runs/RunGovernanceStrip.vue'
import { runFixture } from '@/tests/fixtures/run'

const tailKinds = [
  'verification_passed',
  'compensation_triggered',
  'rpa_executed',
  'reconciliation_found',
  'report_generated',
]

function tailSeqs(): Set<number> {
  return new Set(
    runFixture.events
      .filter((event) => tailKinds.includes(event.kind))
      .map((event) => event.seq),
  )
}

describe('RunGovernanceStrip', () => {
  it('renders five governance chips and reflects visible events', () => {
    const wrapper = mount(RunGovernanceStrip, {
      props: {
        run: runFixture,
        visibleEventSeqs: tailSeqs(),
        activeSeq: null,
      },
    })

    expect(wrapper.findAll('[data-governance-chip]')).toHaveLength(5)
    expect(wrapper.findAll('.governance-chip--done')).toHaveLength(5)
  })

  it('marks future chips and emits seek-event on click', async () => {
    const wrapper = mount(RunGovernanceStrip, {
      props: {
        run: runFixture,
        visibleEventSeqs: new Set<number>(),
        activeSeq: null,
      },
    })

    expect(wrapper.findAll('.governance-chip--future')).toHaveLength(5)
    await wrapper.findAll('[data-governance-chip]')[0].trigger('click')

    const first = runFixture.events.find((event) => event.kind === 'verification_passed')
    expect(wrapper.emitted('seek-event')).toEqual([[first?.seq]])
  })
})
