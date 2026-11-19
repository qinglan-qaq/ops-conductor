import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import RunStepDrawer from '@/features/runs/RunStepDrawer.vue'
import { runFixture } from '@/tests/fixtures/run'

const step = runFixture.steps[4]
const agent = runFixture.agents.find((item) => item.id === step.agent_id)!
const artifact = runFixture.artifacts.find((item) => item.step_id === step.id) ?? null
const gate = runFixture.gates.find((item) => item.step_id === step.id) ?? null
const previous = runFixture.steps[3]
const next = runFixture.steps[5]

function mountDrawer() {
  return mount(RunStepDrawer, {
    props: {
      step,
      agent,
      artifact,
      gate,
      gateStatus: 'pending',
      previous,
      next,
    },
    global: { stubs: { teleport: true } },
  })
}

afterEach(() => {
  document.body.classList.remove('drawer-locked')
})

describe('RunStepDrawer', () => {
  it('shows agent, tool call, artifact, gate and upstream/downstream', () => {
    const wrapper = mountDrawer()

    expect(wrapper.find('[data-step-drawer]').exists()).toBe(true)
    expect(wrapper.text()).toContain(agent.name)
    expect(wrapper.findAll('[data-tool-call]')).toHaveLength(1)
    expect(wrapper.text()).toContain(step.tool_calls[0].tool)
    expect(wrapper.text()).toContain(artifact?.uri ?? '')
    expect(wrapper.find('[data-upstream]').text()).toContain(previous.name)
    expect(wrapper.find('[data-downstream]').text()).toContain(next.name)

    wrapper.unmount()
  })

  it('closes on Escape', async () => {
    const wrapper = mountDrawer()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()

    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
