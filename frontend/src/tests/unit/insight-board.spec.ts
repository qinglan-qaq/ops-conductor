import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InsightBoard from '@/features/overview/InsightBoard.vue'
import { fallbackSnapshot } from '@/api/fixtures'
import { useUiStore } from '@/stores/ui'

const RouterLinkStub = {
  props: ['to'],
  template: '<a :href="String(to)"><slot /></a>',
}

describe('InsightBoard', () => {
  it('renders seven sales points, eight agents and ten stage results', () => {
    const wrapper = mount(InsightBoard, {
      props: { analytics: fallbackSnapshot.analytics },
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: RouterLinkStub },
      },
    })

    expect(wrapper.findAll('[data-sales-point]')).toHaveLength(7)
    expect(wrapper.findAll('[data-agent-usage]')).toHaveLength(8)
    expect(wrapper.findAll('[data-result-stage]')).toHaveLength(10)
    expect(wrapper.text()).toContain('$99,600')
    expect(wrapper.text()).toContain('99.6%')
    expect(wrapper.text()).toContain('10/10')
    expect(wrapper.text()).toContain('20 产物')
    expect(wrapper.text()).toContain('MOCK')
  })

  it('filters the agent panel when a usage row is clicked', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(InsightBoard, {
      props: { analytics: fallbackSnapshot.analytics },
      global: {
        plugins: [pinia],
        stubs: { RouterLink: RouterLinkStub },
      },
    })

    await wrapper.get('[data-agent-usage="order"]').trigger('click')

    const ui = useUiStore()
    expect(ui.selectedAgentId).toBe('order')
    expect(
      wrapper.get('[data-agent-usage="order"]').attributes('aria-pressed'),
    ).toBe('true')
  })
})
