<script setup lang="ts">
import { computed, ref } from 'vue'
import { fallbackSnapshot } from '@/api/fixtures'
import { useSnapshotQuery } from '@/queries/useSnapshotQuery'
import {
  useDecisionMutation,
  useResetApprovalsMutation,
} from '@/queries/mutations'
import { useToast } from '@/composables/useToast'
import ApprovalCard from './ApprovalCard.vue'

const snapshotQuery = useSnapshotQuery()
const decisionMutation = useDecisionMutation()
const resetMutation = useResetApprovalsMutation()
const toast = useToast()
const busyId = ref<string | null>(null)

const snapshot = computed(() => snapshotQuery.data.value ?? fallbackSnapshot)
const approvals = computed(() => Object.values(snapshot.value.approvals))
const pendingCount = computed(
  () => approvals.value.filter((item) => item.status === 'pending').length,
)

function decide(approvalId: string, decision: 'approve' | 'reject'): void {
  busyId.value = approvalId
  decisionMutation.mutate(
    { approvalId, decision },
    {
      onSuccess: (data) => {
        toast.show(
          decision === 'approve'
            ? `已批准 · ${data.approval.title}`
            : `已驳回 · ${data.approval.title}`,
          decision === 'approve' ? 'ink' : 'red',
        )
      },
      onError: (error) => toast.show(`审批失败：${error.message}`, 'red'),
      onSettled: () => {
        busyId.value = null
      },
    },
  )
}

function resetAll(): void {
  resetMutation.mutate(undefined, {
    onSuccess: () => toast.show('审批案已重置 · 3 件待批', 'ink'),
    onError: (error) => toast.show(`重置失败：${error.message}`, 'red'),
  })
}
</script>

<template>
  <div class="page" data-approvals-view>
    <header class="page-head">
      <div>
        <p class="page-kicker">Approvals · 批阅</p>
        <h1>审批案</h1>
        <p class="page-lede">
          L2 二次确认、L3 人工审批；裁决即写 trace，不自动执行剧本建议。
        </p>
      </div>
      <div class="page-head-actions">
        <span class="mono">待批 {{ pendingCount }} / {{ approvals.length }}</span>
        <button
          class="button button-quiet"
          type="button"
          :disabled="resetMutation.isPending.value"
          @click="resetAll"
        >
          重置审批案
        </button>
      </div>
    </header>

    <div class="approval-list">
      <ApprovalCard
        v-for="approval in approvals"
        :key="approval.id"
        :approval="approval"
        :busy="busyId === approval.id"
        @decide="decide"
      />
    </div>
  </div>
</template>
