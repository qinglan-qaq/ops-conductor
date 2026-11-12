<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { Approval, StageResult } from '@/api/types'
import StatusDot from '@/components/ui/StatusDot.vue'
import ArtifactList from './ArtifactList.vue'
import MetricList from './MetricList.vue'
import EvidenceList from './EvidenceList.vue'

const props = defineProps<{
  result: StageResult | null
  agentName: string
  approvals: Approval[]
}>()

const expanded = ref(false)
const pendingApprovals = computed(() =>
  props.approvals.filter((approval) => approval.status === 'pending'),
)
const longSummary = computed(
  () => (props.result?.summary.length ?? 0) > 48,
)
</script>

<template>
  <section class="stage-column panel stage-result-panel" aria-label="Agent 产出">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">Agent 产出</p>
        <h2>{{ result ? agentName : '本阶段暂无产出' }}</h2>
      </div>
      <div v-if="result" class="stage-result-badges">
        <StatusDot :status="result.status" show-label />
        <span class="verifier-badge">Verifier · 独立验证</span>
      </div>
    </header>

    <template v-if="result">
      <div class="stage-result" data-stage-result>
        <p class="result-label">摘要</p>
        <p class="result-summary" :class="{ 'is-clamped': longSummary && !expanded }">
          {{ result.summary }}
        </p>
        <button
          v-if="longSummary"
          class="text-button"
          type="button"
          :aria-expanded="expanded"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起摘要' : '展开摘要' }}
        </button>

        <div class="result-block">
          <p class="result-label">产物</p>
          <ArtifactList :artifacts="result.artifacts" />
        </div>

        <div class="result-block">
          <p class="result-label">指标</p>
          <MetricList :metrics="result.metrics" />
        </div>

        <div class="result-block">
          <p class="result-label">证据</p>
          <EvidenceList :evidence="result.evidence" />
        </div>

        <dl class="source-line">
          <div>
            <dt>来源</dt>
            <dd>{{ result.source.platform }} / {{ result.source.shop_id }}</dd>
          </div>
          <div>
            <dt>Adapter</dt>
            <dd>{{ result.source.adapter }}</dd>
          </div>
          <div>
            <dt>同步</dt>
            <dd class="mono">{{ result.source.synced_at }}</dd>
          </div>
          <div>
            <dt>Schema</dt>
            <dd class="mono">{{ result.source.schema_version }}</dd>
          </div>
        </dl>

        <div class="result-actions">
          <RouterLink
            v-if="pendingApprovals.length"
            class="button button-approve"
            to="/dispatch/approvals"
          >
            去审批（{{ pendingApprovals.length }}）
          </RouterLink>
          <RouterLink class="button button-quiet" :to="{ path: '/dispatch', hash: '#trace' }">
            查看 trace
          </RouterLink>
        </div>
      </div>
    </template>

    <p v-else class="empty-state" data-stage-result-empty>
      本阶段暂无产出。Agent 尚未执行或结果未归档。
    </p>
  </section>
</template>
