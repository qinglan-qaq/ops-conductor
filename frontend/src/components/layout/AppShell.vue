<script setup lang="ts">
import { nextTick, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { IntegrationsResponse, Snapshot } from '@/api/types'
import { useUiStore } from '@/stores/ui'
import AppTopbar from './AppTopbar.vue'
import AppSidebar from './AppSidebar.vue'
import ToastHost from '@/components/ui/ToastHost.vue'

defineProps<{
  snapshot: Snapshot
  integrations: IntegrationsResponse
  offline: boolean
  loading: boolean
}>()

const ui = useUiStore()
const route = useRoute()

watch(
  () => route.fullPath,
  () => {
    ui.closeSidebar()
  },
)

watch(
  () => ui.sidebarOpen,
  async (open) => {
    document.body.classList.toggle('drawer-locked', open)
    await nextTick()
    if (open) {
      document
        .querySelector<HTMLElement>('.app-sidebar .sidebar-close')
        ?.focus()
    } else {
      document.querySelector<HTMLElement>('.catalog-button')?.focus()
    }
  },
)

function focusableSidebarItems(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(
      '.app-sidebar a[href], .app-sidebar button:not(:disabled)',
    ),
  ).filter((element) => element.offsetParent !== null)
}

function onKeydown(event: KeyboardEvent): void {
  if (!ui.sidebarOpen) return
  if (event.key === 'Escape') {
    ui.closeSidebar()
    return
  }
  if (event.key !== 'Tab') return

  const items = focusableSidebarItems()
  if (items.length === 0) return
  const first = items[0]
  const last = items[items.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

window.addEventListener('keydown', onKeydown)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.classList.remove('drawer-locked')
})
</script>

<template>
  <div class="app-shell">
    <AppTopbar
      :pending="snapshot.approval_progress.pending"
      :offline="offline"
      :loading="loading"
      :store="snapshot.goal.store"
      :sidebar-open="ui.sidebarOpen"
      @toggle-sidebar="ui.toggleSidebar()"
    />

    <div class="shell-body">
      <aside
        class="app-sidebar"
        :class="{ 'is-open': ui.sidebarOpen }"
        data-sidebar
      >
        <AppSidebar :navigation="snapshot.navigation" />
      </aside>

      <button
        v-if="ui.sidebarOpen"
        class="sidebar-overlay"
        type="button"
        aria-label="关闭场景目录"
        tabindex="-1"
        @click="ui.closeSidebar()"
      />

      <main id="main-content" class="shell-main">
        <div v-if="offline" class="offline-banner" role="status">
          <strong>离线数据</strong>
          <span>后端未连接，当前展示打包的 Mock 种子；审批与写入不可用。</span>
        </div>
        <slot />
      </main>
    </div>

    <ToastHost />
  </div>
</template>
