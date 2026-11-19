import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunHandoffLedger from '@/features/runs/RunHandoffLedger.vue'
import { runFixture } from '@/tests/fixtures/run'

describe('RunHandoffLedger', () => {
  it('renders eight handoff rows and seeks to their events', async () => {
    const wrapper = mount(RunHandoffLedger, { props: { run: runFixture } })
    const rows = wrapper.findAll('[data-handoff-row]')

    expect(rows).toHaveLength(8)
    expect(rows[0].text()).toContain('选品 Agent → 内容 Agent')
    await rows[0].trigger('click')

    expect(wrapper.emitted('seek-event')).toEqual([[runFixture.handoffs[0].event_seq]])
  })

  it('opens the receiving step from a row', async () => {
    const wrapper = mount(RunHandoffLedger, { props: { run: runFixture } })

    await wrapper.findAll('[aria-label^="查看"]')[0].trigger('click')

    expect(wrapper.emitted('open-step')).toEqual([[runFixture.handoffs[0].to_step_id]])
  })
})
