<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ metrics: Record<string, string | number> }>()

const labels: Record<string, string> = {
  hero_skus: 'Hero SKU',
  vetoed: '否决',
  briefs: 'Brief',
  images: '商品图',
  videos: '短视频',
  listings: 'Listing',
  price_changes: '调价建议',
  planned_posts: '计划内容',
  creators: '达人',
  campaigns: 'Campaign',
  budget: '预算 USD',
  roas: 'ROAS',
  exceptions: '异常单',
  p0_p1: 'P0/P1',
  sla_minutes: 'SLA 分钟',
  compensations: '补偿',
  reservations_released: '释放预占',
  customs_failures: '扣关',
  diffs: '对账差异',
  pending_approvals: '待批',
  vetoed_skus: '剔除 SKU',
}

const entries = computed(() =>
  Object.entries(props.metrics).map(([key, value]) => ({
    key,
    label: labels[key] ?? key,
    value: String(value),
  })),
)
</script>

<template>
  <dl class="metric-list">
    <div v-for="entry in entries" :key="entry.key" class="metric-item">
      <dt>{{ entry.label }}</dt>
      <dd class="mono">{{ entry.value }}</dd>
    </div>
  </dl>
</template>
