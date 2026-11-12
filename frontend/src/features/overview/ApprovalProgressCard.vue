<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { ApprovalProgress } from '@/api/types'

const props = defineProps<{ progress: ApprovalProgress }>()

const decided = computed(() => props.progress.approved + props.progress.rejected)
const approvedWidth = computed(() =>
  props.progress.total ? (props.progress.approved / props.progress.total) * 100 : 0,
)
const rejectedWidth = computed(() =>
  props.progress.total ? (props.progress.rejected / props.progress.total) * 100 : 0,
)
</script>

<template>
  <section class="board-card" data-approval-progress>
    <header class="board-card-head">
      <div>
        <p class="board-kicker">审批进度</p>
        <h2>{{ decided }}/{{ progress.total }} 已批</h2>
      </div>
      <RouterLink class="text-link" to="/dispatch/approvals">审批案 →</RouterLink>
    </header>

    <div
      class="segmented-progress"
      role="progressbar"
      :aria-valuenow="progress.decided_percent"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-label="审批完成比例"
    >
      <span
        class="segment segment-approved"
        :style="{ width: `${approvedWidth}%` }"
      />
      <span
        class="segment segment-rejected"
        :style="{ width: `${rejectedWidth}%` }"
      />
      <span class="segment segment-pending" />
    </div>

    <dl class="board-legend">
      <div>
        <dt><i class="legend-mark legend-pending" />待批</dt>
        <dd>{{ progress.pending }}</dd>
      </div>
      <div>
        <dt><i class="legend-mark legend-approved" />已准</dt>
        <dd>{{ progress.approved }}</dd>
      </div>
      <div>
        <dt><i class="legend-mark legend-rejected" />已驳</dt>
        <dd>{{ progress.rejected }}</dd>
      </div>
    </dl>

    <footer class="board-footnote">
      <span>L2 × {{ progress.l2_total }}</span>
      <span>L3 × {{ progress.l3_total }}</span>
      <span>{{ progress.decided_percent }}% 已裁决</span>
    </footer>
  </section>
</template>
