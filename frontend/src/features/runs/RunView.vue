<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/errors'
import { useRunQuery } from '@/queries/useRunQuery'
import RunBody from './RunBody.vue'

const route = useRoute()
const runId = computed(() => {
  const value = route.params.runId
  return typeof value === 'string' ? value : null
})
const runQuery = useRunQuery(runId)
const notFound = computed(
  () => runQuery.error.value instanceof ApiError && runQuery.error.value.status === 404,
)
const error = computed(() => runQuery.error.value)
</script>

<template>
  <div class="page run-page" data-run-view>
    <div v-if="runQuery.isPending.value" class="run-state" aria-busy="true">
      <p class="page-kicker">Agent Run</p>
      <h1>正在读取运行记录…</h1>
      <p class="section-note">加载步骤、事件、工具调用与审批门禁。</p>
    </div>

    <div v-else-if="notFound" class="run-state" data-run-not-found>
      <p class="page-kicker">404 · Run</p>
      <h1>这条运行记录不存在</h1>
      <p class="section-note">它可能已被重置，或链接有误。</p>
      <RouterLink class="button button-primary" to="/dispatch">返回今日态势</RouterLink>
    </div>

    <div v-else-if="error" class="run-state" data-run-error>
      <p class="page-kicker">Run unavailable</p>
      <h1>运行记录读取失败</h1>
      <p class="section-note">{{ error.message }}</p>
      <button class="button button-primary" type="button" @click="runQuery.refetch()">
        重试
      </button>
    </div>

    <RunBody v-else-if="runQuery.data.value" :run="runQuery.data.value" />
  </div>
</template>
