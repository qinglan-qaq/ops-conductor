<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

const props = defineProps<{
  pending: number
  offline: boolean
  loading: boolean
  store: string
  sidebarOpen: boolean
}>()

const emit = defineEmits<{ 'toggle-sidebar': [] }>()

const statusLabel = computed(() => {
  if (props.offline) return '离线数据'
  if (props.loading) return '连接中'
  return '后端已连接'
})

const statusClass = computed(() => {
  if (props.offline) return 'is-offline'
  if (props.loading) return 'is-loading'
  return 'is-online'
})

const today = new Intl.DateTimeFormat('zh-CN', {
  month: 'long',
  day: 'numeric',
  weekday: 'short',
}).format(new Date())
</script>

<template>
  <header class="app-topbar">
    <div class="brand">
      <span class="brand-seal" aria-hidden="true">运筹</span>
      <div class="brand-copy">
        <RouterLink class="brand-title" to="/dispatch">统一台前调度</RouterLink>
        <span class="brand-sub">{{ store }} · 跨境运营操作系统</span>
      </div>
    </div>

    <div class="topbar-meta">
      <span class="topbar-date">{{ today }}</span>
      <span class="api-status" :class="statusClass">
        <span class="api-dot" aria-hidden="true" />
        {{ statusLabel }}
      </span>
      <RouterLink class="pending-link" to="/dispatch/approvals">
        待批 <strong>{{ pending }}</strong>
      </RouterLink>
      <button
        class="catalog-button"
        type="button"
        aria-label="打开场景目录"
        :aria-expanded="sidebarOpen"
        @click="emit('toggle-sidebar')"
      >
        目录
      </button>
    </div>
  </header>
</template>
