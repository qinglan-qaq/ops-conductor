import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StageResultPanel from '@/features/stage/StageResultPanel.vue'
import { fallbackStageDetails } from '@/api/fixtures'

const RouterLinkStub = {
  props: ['to'],
  template: '<a :href="String(to)"><slot /></a>',
}

describe('StageResultPanel', () => {
  it('renders the order agent summary, artifacts, metrics and source', () => {
    const detail = fallbackStageDetails.order

    const wrapper = mount(StageResultPanel, {
      props: {
        result: detail.result,
        agentName: '订单 Agent',
        approvals: detail.approvals,
      },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })

    expect(wrapper.text()).toContain('分类 6 单异常')
    expect(wrapper.text()).toContain('order-exceptions.csv')
    expect(wrapper.text()).toContain('异常单')
    expect(wrapper.text()).toContain('6')
    expect(wrapper.text()).toContain('MockPlatformAdapter')
    expect(wrapper.text()).toContain('nestwell-us')
  })

  it('renders an explicit empty state without fake results', () => {
    const wrapper = mount(StageResultPanel, {
      props: { result: null, agentName: '订单 Agent', approvals: [] },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })

    expect(wrapper.text()).toContain('本阶段暂无产出')
  })
})
