import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import { fallbackSnapshot } from '@/api/fixtures'

const Empty = { template: '<div />' }

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/dispatch', name: 'overview', component: Empty },
      {
        path: '/dispatch/stages/:stageId',
        name: 'stage',
        component: Empty,
      },
      { path: '/dispatch/approvals', name: 'approvals', component: Empty },
      { path: '/dispatch/exceptions', name: 'exceptions', component: Empty },
      { path: '/dispatch/integrations', name: 'integrations', component: Empty },
    ],
  })
}

describe('AppSidebar', () => {
  it('renders ten stages plus the control tower in order', async () => {
    const router = makeRouter()
    await router.push('/dispatch/stages/order')
    await router.isReady()

    const wrapper = mount(AppSidebar, {
      props: { navigation: fallbackSnapshot.navigation },
      global: {
        plugins: [createPinia(), router],
      },
    })

    const groups = wrapper.findAll('[data-sidebar-group]')
    expect(groups).toHaveLength(11)
    expect(groups[0].attributes('data-sidebar-group')).toBe('selection')
    expect(groups[10].attributes('data-sidebar-group')).toBe('control')

    const current = wrapper.find('[data-sidebar-group="order"] a[aria-current="page"]')
    expect(current.exists()).toBe(true)
    expect(wrapper.text()).toContain('6 单异常')
  })
})
