<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fallbackSnapshot } from '@/api/fixtures'
import type { ExceptionCase, Priority } from '@/api/types'
import { useSnapshotQuery } from '@/queries/useSnapshotQuery'
import ExceptionDrawer from './ExceptionDrawer.vue'

const snapshotQuery = useSnapshotQuery()
const route = useRoute()
const router = useRouter()
const active = ref<ExceptionCase | null>(null)

const priorities: Array<Priority | 'ALL'> = ['ALL', 'P0', 'P1', 'P2', 'P3']
const snapshot = computed(() => snapshotQuery.data.value ?? fallbackSnapshot)

const filter = computed<Priority | 'ALL'>(() => {
  const value = route.query.priority
  return value === 'P0' || value === 'P1' || value === 'P2' || value === 'P3'
    ? value
    : 'ALL'
})

const exceptions = computed(() =>
  filter.value === 'ALL'
    ? snapshot.value.exceptions
    : snapshot.value.exceptions.filter(
        (exception) => exception.priority === filter.value,
      ),
)

function setFilter(priority: Priority | 'ALL'): void {
  router.replace({
    name: 'exceptions',
    query: priority === 'ALL' ? {} : { priority },
  })
}
</script>

<template>
  <div class="page" data-exceptions-view>
    <header class="page-head">
      <div>
        <p class="page-kicker">Exceptions · 异常簿</p>
        <h1>异常与 Playbook</h1>
        <p class="page-lede">
          按 5×5 矩阵定级；点击任一异常查看 0–72 小时处置与 Agent 自动化边界。
        </p>
      </div>
      <span class="page-count mono">{{ exceptions.length }} / {{ snapshot.exceptions.length }}</span>
    </header>

    <div class="filter-row" role="group" aria-label="按优先级筛选">
      <button
        v-for="priority in priorities"
        :key="priority"
        class="filter-chip"
        type="button"
        :class="{ 'is-active': filter === priority }"
        :aria-pressed="filter === priority"
        @click="setFilter(priority)"
      >
        {{ priority === 'ALL' ? '全部' : priority }}
      </button>
    </div>

    <ul class="exception-list">
      <li v-for="exception in exceptions" :key="exception.id">
        <button
          class="exception-row"
          type="button"
          :data-exception-id="exception.id"
          @click="active = exception"
        >
          <span
            class="priority-code"
            :class="`priority-code--${exception.priority.toLowerCase()}`"
          >
            {{ exception.priority }}
          </span>
          <span class="exception-main">
            <strong>{{ exception.title }}</strong>
            <small>{{ exception.id }} · {{ exception.owner }} · {{ exception.count }}</small>
          </span>
          <span class="exception-sla">{{ exception.sla }}</span>
          <span class="exception-stage mono">{{ exception.stage_id || '全局' }}</span>
        </button>
      </li>
    </ul>
    <p v-if="exceptions.length === 0" class="empty-state">该优先级下暂无异常。</p>

    <ExceptionDrawer
      v-if="active"
      :exception="active"
      @close="active = null"
    />
  </div>
</template>
