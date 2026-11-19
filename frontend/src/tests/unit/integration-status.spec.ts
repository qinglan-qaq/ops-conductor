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
    expect(wrapper.find('[data-credential-status]').text()).toContain('未要求')
  })

  it('shows configured and missing credential states without a ref', () => {
    const base = fallbackIntegrations.platforms[0]
    const configured = mount(IntegrationStatus, {
      props: { platform: { ...base, credential_status: 'configured' } },
    })
    const missing = mount(IntegrationStatus, {
      props: { platform: { ...base, credential_status: 'missing' } },
    })

    expect(configured.find('[data-credential-status]').text()).toContain('已配置')
    expect(missing.find('[data-credential-status]').text()).toContain('缺失')
    expect(configured.text()).not.toContain('credential_ref')
    expect(missing.text()).not.toContain('credential_ref')
  })
})
