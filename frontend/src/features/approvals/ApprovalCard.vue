<script setup lang="ts">
import type { Approval } from '@/api/types'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import Seal from '@/components/ui/Seal.vue'

defineProps<{
  approval: Approval
  busy?: boolean
}>()

const emit = defineEmits<{
  decide: [approvalId: string, decision: 'approve' | 'reject']
}>()

function stampTone(approval: Approval): 'approve' | 'reject' | 'pending' {
  if (approval.status === 'approved') return 'approve'
  if (approval.status === 'rejected') return 'reject'
  return 'pending'
}
</script>

<template>
  <article class="approval-card" :data-approval-id="approval.id">
    <div class="approval-card-top">
      <div>
        <div class="approval-title-row">
          <RiskBadge :risk="approval.risk" />
          <h3>{{ approval.title }}</h3>
        </div>
        <p class="approval-action mono">{{ approval.action }}</p>
      </div>
      <Seal
        :text="approval.stamp ?? '待'"
        :tone="stampTone(approval)"
      />
    </div>

    <dl class="approval-facts">
      <div>
        <dt>责任人</dt>
        <dd>{{ approval.owner }}</dd>
      </div>
      <div>
        <dt>影响</dt>
        <dd>{{ approval.impact }}</dd>
      </div>
      <div>
        <dt>阶段</dt>
        <dd>{{ approval.stage_id || '全局' }}</dd>
      </div>
    </dl>

    <p v-if="approval.status === 'pending' && approval.recommended" class="approval-hint">
      剧本建议：{{ approval.recommended === 'approve' ? '准' : '驳' }} ·
      建议不自动执行
    </p>
    <p v-if="approval.actor" class="approval-decided">
      {{ approval.actor }} 于 {{ approval.decided_at }} 已裁决
    </p>

    <div v-if="approval.status === 'pending'" class="approval-actions">
      <button
        class="button button-approve"
        type="button"
        :disabled="busy"
        :aria-label="`批准 ${approval.title}`"
        @click="emit('decide', approval.id, 'approve')"
      >
        准
      </button>
      <button
        class="button button-reject"
        type="button"
        :disabled="busy"
        :aria-label="`驳回 ${approval.title}`"
        @click="emit('decide', approval.id, 'reject')"
      >
        驳
      </button>
    </div>
  </article>
</template>
