<script setup lang="ts">
import { computed } from 'vue'
import type { AgentCard, StageDetail } from '@/api/types'
import StageHeader from './StageHeader.vue'
import StageFlow from './StageFlow.vue'
import StageResultPanel from './StageResultPanel.vue'
import StageContext from './StageContext.vue'

const props = defineProps<{
  detail: StageDetail
  activeStepId: string | null
  agents: AgentCard[]
}>()

const agentName = computed(() => {
  const agentId = props.detail.result?.agent_id
  if (!agentId) return 'Agent'
  return props.agents.find((agent) => agent.id === agentId)?.name ?? `${agentId} Agent`
})
</script>

<template>
  <div class="stage-workspace" data-stage-workspace>
    <StageHeader :detail="detail" />
    <div class="stage-grid">
      <StageFlow
        :stage-id="detail.id"
        :steps="detail.steps"
        :stage-status="detail.status"
        :active-step-id="activeStepId"
        :owner="detail.owner"
        :risk="detail.risk"
      />
      <StageResultPanel
        :result="detail.result"
        :agent-name="agentName"
        :approvals="detail.approvals"
      />
      <StageContext :detail="detail" />
    </div>
  </div>
</template>
