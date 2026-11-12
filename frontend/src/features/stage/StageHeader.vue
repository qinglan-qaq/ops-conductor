<script setup lang="ts">
import type { StageDetail } from '@/api/types'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import StatusDot from '@/components/ui/StatusDot.vue'

defineProps<{ detail: StageDetail }>()
</script>

<template>
  <header class="stage-header" data-stage-header>
    <div class="stage-title">
      <span class="stage-order-large" aria-hidden="true">
        {{ detail.order_label }}
      </span>
      <div>
        <p class="page-kicker">Stage · {{ detail.id }}</p>
        <h1>{{ detail.name }}</h1>
        <p class="stage-lede">{{ detail.meta }} · {{ detail.owner }}</p>
      </div>
    </div>
    <div class="stage-badges">
      <StatusDot :status="detail.status" show-label />
      <RiskBadge :risk="detail.risk" />
      <span class="stage-badge-note">
        审批 {{ detail.approvals.length }} · 异常 {{ detail.exceptions.length }}
      </span>
    </div>
  </header>
</template>
