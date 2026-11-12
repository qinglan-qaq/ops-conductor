<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { fallbackSnapshot, fallbackStageDetails } from '@/api/fixtures'
import { ApiError } from '@/api/client'
import { useSnapshotQuery } from '@/queries/useSnapshotQuery'
import { useStageDetailQuery } from '@/queries/useStageDetailQuery'
import StageWorkspace from './StageWorkspace.vue'

const props = defineProps<{ stageId: string }>()

const route = useRoute()
const snapshotQuery = useSnapshotQuery()
const stageQuery = useStageDetailQuery(computed(() => props.stageId))

const snapshot = computed(() => snapshotQuery.data.value ?? fallbackSnapshot)
const activeStepId = computed(() => {
  const value = route.query.step
  return typeof value === 'string' ? value : null
})
const notFound = computed(
  () => stageQuery.error.value instanceof ApiError && stageQuery.error.value.status === 404,
)
const offline = computed(
  () => stageQuery.isError.value && !notFound.value,
)
const detail = computed(() => {
  if (stageQuery.data.value) return stageQuery.data.value
  if (offline.value) return fallbackStageDetails[props.stageId] ?? null
  return null
})
</script>

<template>
  <div class="page" data-stage-view>
    <div v-if="stageQuery.isPending.value" class="stage-skeleton" aria-busy="true">
      <span class="skeleton-line skeleton-title" />
      <span class="skeleton-line" />
      <span class="skeleton-line skeleton-short" />
    </div>

    <div v-else-if="notFound" class="empty-state" data-stage-not-found>
      <p class="page-kicker">404 · 阶段不存在</p>
      <h1>没有找到阶段「{{ stageId }}」</h1>
      <p class="section-note">控制塔使用集成健康与首页聚合数据，不提供阶段详情。</p>
      <RouterLink class="button button-primary" to="/dispatch">回到总览</RouterLink>
    </div>

    <template v-else-if="detail">
      <div v-if="offline" class="inline-offline" role="status">
        阶段详情读取失败，正在展示打包的离线 fixture。
        <button class="text-button" type="button" @click="stageQuery.refetch()">
          重试
        </button>
      </div>
      <StageWorkspace
        :detail="detail"
        :active-step-id="activeStepId"
        :agents="snapshot.agents"
      />
    </template>

    <div v-else class="empty-state" data-stage-error>
      <p class="page-kicker">阶段详情加载失败</p>
      <h1>无法读取阶段</h1>
      <p class="section-note">{{ stageQuery.error.value?.message ?? '未知错误' }}</p>
      <button class="button button-primary" type="button" @click="stageQuery.refetch()">
        重试
      </button>
    </div>
  </div>
</template>
