<script setup lang="ts">
import type { RunListItem } from '@/api/types'

defineProps<{
  runs: RunListItem[]
  loading: boolean
  error: boolean
}>()

const emit = defineEmits<{
  (event: 'open', runId: string): void
  (event: 'start'): void
}>()

function statusLabel(status: RunListItem['status']): string {
  if (status === 'succeeded') return '已完成'
  if (status === 'failed') return '失败'
  return '进行中'
}
</script>

<template>
  <section class="panel recent-runs-card" data-recent-runs aria-label="最近运行">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">最近运行</p>
        <h2>{{ runs.length }} 条记录</h2>
      </div>
      <button class="text-button" type="button" @click="emit('start')">运行一次</button>
    </header>

    <p v-if="loading" class="section-note">正在读取运行记录…</p>
    <p v-else-if="error" class="section-note" data-recent-runs-error>运行记录暂不可用。</p>
    <div v-else-if="runs.length === 0" class="recent-run-empty" data-recent-runs-empty>
      <p>还没有运行记录。让 8 个 Agent 跑一次，看看谁先接手。</p>
      <button class="button button-primary" type="button" @click="emit('start')">
        运行 Agent 团队
      </button>
    </div>
    <ul v-else class="recent-run-list">
      <li v-for="run in runs" :key="run.id">
        <button class="recent-run-row" type="button" data-recent-run @click="emit('open', run.id)">
          <span class="recent-run-status" :class="`recent-run-status--${run.status}`">
            {{ statusLabel(run.status) }}
          </span>
          <span class="recent-run-main">
            <strong>{{ run.goal_instruction }}</strong>
            <span>{{ run.summary }}</span>
          </span>
          <span class="recent-run-meta mono">
            {{ run.started_at }} · {{ run.step_count }} 步 · {{ run.gate_count }} 门禁
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>
