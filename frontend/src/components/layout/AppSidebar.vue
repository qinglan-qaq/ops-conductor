<script setup lang="ts">
import { computed, watch } from 'vue'
import {
  RouterLink,
  useRoute,
  useRouter,
  type RouteLocationRaw,
} from 'vue-router'
import type { StageNavigation } from '@/api/types'
import { useUiStore } from '@/stores/ui'
import StatusDot from '@/components/ui/StatusDot.vue'

const props = defineProps<{ navigation: StageNavigation[] }>()

const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const currentStageId = computed(() =>
  route.name === 'stage' ? String(route.params.stageId ?? '') : null,
)

watch(
  currentStageId,
  (stageId) => {
    if (stageId) {
      ui.rememberStage(stageId)
    }
  },
  { immediate: true },
)

function isExpanded(stageId: string): boolean {
  return ui.isStageExpanded(stageId) || currentStageId.value === stageId
}

function isGroupActive(item: StageNavigation): boolean {
  if (item.id === 'control') {
    return ['integrations', 'approvals', 'exceptions'].includes(
      String(route.name),
    )
  }
  return currentStageId.value === item.id
}

function groupAriaCurrent(item: StageNavigation): 'page' | undefined {
  if (item.id === 'control') {
    return route.name === 'integrations' ? 'page' : undefined
  }
  return currentStageId.value === item.id && !route.query.step
    ? 'page'
    : undefined
}

function groupTarget(item: StageNavigation) {
  if (item.id === 'control') {
    return { name: 'integrations' }
  }
  return { name: 'stage', params: { stageId: item.id } }
}

function onGroupClick(item: StageNavigation): void {
  if (item.id !== 'control') {
    ui.expandStage(item.id)
  }
  ui.closeSidebar()
}

function isStepActive(item: StageNavigation, stepId: string): boolean {
  if (item.id === 'control') {
    return route.path === controlStepPath(stepId)
  }
  return (
    route.name === 'stage' &&
    currentStageId.value === item.id &&
    route.query.step === stepId
  )
}

function controlStepPath(stepId: string): string {
  const paths: Record<string, string> = {
    metrics: '/dispatch',
    alerts: '/dispatch/exceptions',
    approvals: '/dispatch/approvals',
    trace: '/dispatch',
    retro: '/dispatch',
  }
  return paths[stepId] ?? '/dispatch'
}

function stepTarget(item: StageNavigation, stepId: string) {
  if (item.id === 'control') {
    return controlStepPath(stepId)
  }
  return {
    name: 'stage',
    params: { stageId: item.id },
    query: { step: stepId },
  }
}

function hrefFor(target: RouteLocationRaw): string {
  return router.resolve(target).href
}

function navigate(token: RouteLocationRaw): void {
  void router.push(token)
}

function navigateGroup(item: StageNavigation): void {
  navigate(groupTarget(item))
  onGroupClick(item)
}

function navigateStep(item: StageNavigation, stepId: string): void {
  navigate(stepTarget(item, stepId))
  ui.closeSidebar()
}
</script>

<template>
  <nav class="sidebar-nav" aria-label="场景目录">
    <div class="sidebar-heading">
      <span class="sidebar-kicker">卷宗目录</span>
      <span class="sidebar-hint">按运营顺序</span>
      <button
        class="sidebar-close"
        type="button"
        aria-label="关闭场景目录"
        @click="ui.closeSidebar()"
      >
        关闭
      </button>
    </div>

    <RouterLink
      class="overview-link"
      to="/dispatch"
      :aria-current="route.name === 'overview' ? 'page' : undefined"
      @click="ui.closeSidebar()"
    >
      <span class="overview-mark" aria-hidden="true">总</span>
      <span>
        <strong>今日态势</strong>
        <small>审批 · 链路 · 异常</small>
      </span>
    </RouterLink>

    <div class="sidebar-groups">
      <section
        v-for="item in props.navigation"
        :key="item.id"
        class="stage-group"
        :class="{ 'is-active': isGroupActive(item) }"
        :data-sidebar-group="item.id"
      >
        <div class="stage-group-head">
          <a
            class="stage-group-link"
            :href="hrefFor(groupTarget(item))"
            :aria-current="groupAriaCurrent(item)"
            @click.prevent="navigateGroup(item)"
          >
            <span class="stage-order">{{ item.order_label }}</span>
            <span class="stage-name">{{ item.name }}</span>
            <span class="stage-meta">{{ item.meta }}</span>
            <StatusDot :status="item.status" />
          </a>
          <button
            class="stage-toggle"
            type="button"
            :aria-label="`${isExpanded(item.id) ? '收起' : '展开'} ${item.name}`"
            :aria-expanded="isExpanded(item.id)"
            @click="ui.toggleStage(item.id)"
          >
            {{ isExpanded(item.id) ? '−' : '+' }}
          </button>
        </div>

        <div v-if="item.approval_count > 0 || item.exception_count > 0" class="stage-counts">
          <span v-if="item.approval_count > 0" class="count count-gold">
            待批 {{ item.approval_count }}
          </span>
          <span v-if="item.exception_count > 0" class="count count-red">
            异常 {{ item.exception_count }}
          </span>
        </div>

        <ul v-show="isExpanded(item.id)" class="stage-steps">
          <li v-for="step in item.steps" :key="step.id">
            <a
              :href="hrefFor(stepTarget(item, step.id))"
              class="stage-step-link"
              :aria-current="isStepActive(item, step.id) ? 'page' : undefined"
              @click.prevent="navigateStep(item, step.id)"
            >
              <span class="step-tick" aria-hidden="true" />
              {{ step.name }}
            </a>
          </li>
        </ul>
      </section>
    </div>
  </nav>
</template>
