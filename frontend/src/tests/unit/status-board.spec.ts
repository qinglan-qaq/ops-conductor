import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import StatusBoard from '@/features/overview/StatusBoard.vue'
import { fallbackIntegrations, fallbackSnapshot } from '@/api/fixtures'

const RouterLinkStub = {
  props: ['to'],
  template: '<a :href="String(to)"><slot /></a>',
}

describe('StatusBoard', () => {
  it('shows approval progress, ten chain stages, agents and priorities', () => {
    const wrapper = mount(StatusBoard, {
      props: {
        snapshot: fallbackSnapshot,
        integrations: fallbackIntegrations,
      },
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: RouterLinkStub },
      },
    })

    expect(wrapper.text()).toContain('0/3 已批')
    expect(wrapper.findAll('[data-chain-stage]')).toHaveLength(10)
    expect(wrapper.findAll('[data-agent-id]')).toHaveLength(8)
    expect(wrapper.text()).toContain('P0')
    expect(wrapper.text()).toContain('NestWell Home US')
  })
})
