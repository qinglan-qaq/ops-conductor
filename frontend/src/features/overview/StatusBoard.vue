<script setup lang="ts">
import type { IntegrationsResponse, Snapshot } from '@/api/types'
import ApprovalProgressCard from './ApprovalProgressCard.vue'
import ChainMatrix from './ChainMatrix.vue'
import AgentStatusGrid from './AgentStatusGrid.vue'
import ExceptionDistribution from './ExceptionDistribution.vue'
import IntegrationHealthCard from './IntegrationHealthCard.vue'

defineProps<{
  snapshot: Snapshot
  integrations: IntegrationsResponse
}>()
</script>

<template>
  <div class="status-board" data-status-board>
    <ApprovalProgressCard :progress="snapshot.approval_progress" />
    <ChainMatrix :chain="snapshot.chain" />
    <ExceptionDistribution
      :distribution="snapshot.status_summary.exceptions"
    />
    <AgentStatusGrid
      :agents="snapshot.agents"
      :summary="snapshot.status_summary.agents"
    />
    <IntegrationHealthCard :integrations="integrations" />
  </div>
</template>
