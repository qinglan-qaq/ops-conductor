<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { Priority, StatusSummary } from '@/api/types'

defineProps<{ distribution: StatusSummary['exceptions'] }>()

const priorities: Priority[] = ['P0', 'P1', 'P2', 'P3']
const sla: Record<Priority, string> = {
  P0: '15m',
  P1: '30m',
  P2: '4h',
  P3: '24h',
}
</script>

<template>
  <section class="board-card" data-exception-distribution>
    <header class="board-card-head">
      <div>
        <p class="board-kicker">异常分布</p>
        <h2>按优先级</h2>
      </div>
      <RouterLink class="text-link" to="/dispatch/exceptions">异常簿 →</RouterLink>
    </header>

    <div class="priority-rows">
      <RouterLink
        v-for="priority in priorities"
        :key="priority"
        class="priority-row"
        :class="`priority-row--${priority.toLowerCase()}`"
        :to="{ name: 'exceptions', query: { priority } }"
      >
        <span class="priority-code">{{ priority }}</span>
        <span class="priority-count">{{ distribution[priority] ?? 0 }}</span>
        <span class="priority-sla">{{ sla[priority] }}</span>
      </RouterLink>
    </div>
  </section>
</template>
