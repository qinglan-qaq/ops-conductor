import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dispatch' },
  {
    path: '/dispatch',
    name: 'overview',
    component: () => import('@/features/overview/OverviewView.vue'),
    meta: { title: '今日态势' },
  },
  {
    path: '/dispatch/stages/:stageId',
    name: 'stage',
    component: () => import('@/features/stage/StageView.vue'),
    props: true,
    meta: { title: '阶段工作台' },
  },
  {
    path: '/dispatch/approvals',
    name: 'approvals',
    component: () => import('@/features/approvals/ApprovalsView.vue'),
    meta: { title: '审批案' },
  },
  {
    path: '/dispatch/exceptions',
    name: 'exceptions',
    component: () => import('@/features/exceptions/ExceptionsView.vue'),
    meta: { title: '异常簿' },
  },
  {
    path: '/dispatch/integrations',
    name: 'integrations',
    component: () => import('@/features/integrations/IntegrationsView.vue'),
    meta: { title: '平台集成' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/dispatch' },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : '统一台前调度'
  document.title = `${title} · 运筹跨境`
})

export default router
