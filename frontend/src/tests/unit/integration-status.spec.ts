import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import IntegrationStatus from '@/features/integrations/IntegrationStatus.vue'
import { fallbackIntegrations } from '@/api/fixtures'

describe('IntegrationStatus', () => {
  it('groups data and control capabilities without platform branches', () => {
    const platform = fallbackIntegrations.platforms[0]

    const wrapper = mount(IntegrationStatus, { props: { platform } })

    expect(wrapper.text()).toContain('NestWell Home US')
    expect(wrapper.text()).toContain('data.orders')
    expect(wrapper.text()).toContain('control.price')
    expect(wrapper.text()).toContain('Mock Adapter 健康')
  })
})
