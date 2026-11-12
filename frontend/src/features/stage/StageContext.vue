<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { StageDetail } from '@/api/types'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import Seal from '@/components/ui/Seal.vue'

defineProps<{ detail: StageDetail }>()

function stampTone(status: string): 'approve' | 'reject' | 'pending' {
  if (status === 'approved') return 'approve'
  if (status === 'rejected') return 'reject'
  return 'pending'
}
</script>

<template>
  <aside class="stage-column stage-context" aria-label="本阶段上下文">
    <section class="context-block panel">
      <header class="panel-head">
        <div>
          <p class="panel-kicker">本阶段审批</p>
          <h2>{{ detail.approvals.length }} 件</h2>
        </div>
        <RouterLink class="text-link" to="/dispatch/approvals">全部 →</RouterLink>
      </header>
      <ul v-if="detail.approvals.length" class="context-approvals">
        <li v-for="approval in detail.approvals" :key="approval.id">
          <div>
            <RiskBadge :risk="approval.risk" />
            <strong>{{ approval.title }}</strong>
          </div>
          <Seal
            :text="approval.stamp ?? '待'"
            :tone="stampTone(approval.status)"
          />
        </li>
      </ul>
      <p v-else class="empty-state">本阶段无审批项。</p>
    </section>

    <section class="context-block panel">
      <header class="panel-head">
        <div>
          <p class="panel-kicker">本阶段异常</p>
          <h2>{{ detail.exceptions.length }} 条</h2>
        </div>
        <RouterLink class="text-link" to="/dispatch/exceptions">异常簿 →</RouterLink>
      </header>
      <ul v-if="detail.exceptions.length" class="context-exceptions">
        <li v-for="exception in detail.exceptions" :key="exception.id">
          <span
            class="priority-code"
            :class="`priority-code--${exception.priority.toLowerCase()}`"
          >
            {{ exception.priority }}
          </span>
          <div>
            <strong>{{ exception.title }}</strong>
            <small>{{ exception.id }} · {{ exception.sla }}</small>
          </div>
        </li>
      </ul>
      <p v-else class="empty-state">本阶段无异常。</p>
    </section>

    <section class="context-block panel">
      <header class="panel-head">
        <div>
          <p class="panel-kicker">上下文</p>
          <h2>证据与文档</h2>
        </div>
      </header>
      <dl class="context-facts">
        <div>
          <dt>阶段动作</dt>
          <dd>{{ detail.actions.join(' / ') }}</dd>
        </div>
        <div>
          <dt>典型失败</dt>
          <dd>{{ detail.failures.join(' / ') }}</dd>
        </div>
        <div>
          <dt>关键指标</dt>
          <dd>{{ detail.metrics.join(' / ') }}</dd>
        </div>
        <div>
          <dt>AI 增强</dt>
          <dd>{{ detail.ai.join(' / ') }}</dd>
        </div>
      </dl>
      <div class="context-links">
        <RouterLink class="text-link" :to="{ path: '/dispatch', hash: '#trace' }">
          trace 审计 →
        </RouterLink>
        <RouterLink class="text-link" to="/dispatch/integrations">
          集成健康 →
        </RouterLink>
      </div>
    </section>
  </aside>
</template>
