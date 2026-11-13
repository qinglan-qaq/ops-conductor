<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { fallbackIntegrations, fallbackSnapshot } from '@/api/fixtures'
import { useSnapshotQuery } from '@/queries/useSnapshotQuery'
import { useIntegrationsQuery } from '@/queries/useIntegrationsQuery'
import {
  useDemoMutation,
  useGoalMutation,
  useResetDispatchMutation,
} from '@/queries/mutations'
import { useUiStore } from '@/stores/ui'
import { useToast } from '@/composables/useToast'
import StatusBoard from './StatusBoard.vue'
import InsightBoard from './InsightBoard.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import TraceTimeline from '@/features/trace/TraceTimeline.vue'

const snapshotQuery = useSnapshotQuery()
const integrationsQuery = useIntegrationsQuery()
const goalMutation = useGoalMutation()
const demoMutation = useDemoMutation()
const resetMutation = useResetDispatchMutation()
const ui = useUiStore()
const toast = useToast()

const snapshot = computed(() => snapshotQuery.data.value ?? fallbackSnapshot)
const integrations = computed(
  () => integrationsQuery.data.value ?? fallbackIntegrations,
)
const instruction = ref(snapshot.value.goal.instruction)
const kpi = computed(() => snapshot.value.kpis)
const agents = computed(() => {
  if (!ui.selectedAgentId) return snapshot.value.agents
  return snapshot.value.agents.filter((agent) => agent.id === ui.selectedAgentId)
})
const pendingApprovals = computed(() =>
  Object.values(snapshot.value.approvals).filter(
    (approval) => approval.status === 'pending',
  ),
)

function submitGoal(): void {
  const text = instruction.value.trim()
  if (!text) {
    toast.show('请先写下一个目标', 'red')
    return
  }
  goalMutation.mutate(text, {
    onSuccess: () => toast.show('计划已生成 · 等待 L2/L3 审批', 'ink'),
    onError: (error) => toast.show(`目标解析失败：${error.message}`, 'red'),
  })
}

function playDemo(): void {
  demoMutation.mutate(undefined, {
    onSuccess: (data) =>
      toast.show(
        `${data.report.summary} · 只读投影，审批状态未改变`,
        'gold',
      ),
    onError: (error) => toast.show(`演示失败：${error.message}`, 'red'),
  })
}

function resetDemo(): void {
  resetMutation.mutate(undefined, {
    onSuccess: () => toast.show('已恢复 Demo 种子 · 3 件待批', 'ink'),
    onError: (error) => toast.show(`重置失败：${error.message}`, 'red'),
  })
}
</script>

<template>
  <div class="page overview-page" data-overview>
    <header class="page-head">
      <div>
        <p class="page-kicker">Today · 今日态势</p>
        <h1>统一台前调度</h1>
        <p class="page-lede">
          目标、审批、十段链路与 Agent 产出在同一张案桌上；
          <span class="mono">{{ snapshot.flow_note }}</span>
        </p>
      </div>
      <div class="page-stamp" aria-hidden="true">
        <span>跨</span><span>境</span><span>调</span><span>度</span>
      </div>
    </header>

    <section class="command-bar" aria-label="调度命令">
      <label class="command-label" for="goal-input">令</label>
      <input
        id="goal-input"
        v-model="instruction"
        class="command-input"
        type="text"
        maxlength="500"
        placeholder="写下一个运营目标，例如：本周做到 $100k GMV"
        @keyup.enter="submitGoal"
      />
      <button
        class="button button-primary"
        type="button"
        :disabled="goalMutation.isPending.value"
        @click="submitGoal"
      >
        {{ goalMutation.isPending.value ? '生成中…' : '生成调度计划' }}
      </button>
      <button
        class="button button-quiet"
        type="button"
        :disabled="demoMutation.isPending.value"
        @click="playDemo"
      >
        播放演示
      </button>
      <button
        class="button button-quiet"
        type="button"
        :disabled="resetMutation.isPending.value"
        @click="resetDemo"
      >
        重置
      </button>
    </section>

    <section class="kpi-strip" aria-label="关键指标">
      <div class="kpi-item">
        <span class="kpi-label">GMV 目标</span>
        <strong class="kpi-value mono">${{ kpi.gmv_target.toLocaleString() }}</strong>
        <span class="kpi-note">{{ snapshot.goal.market }}</span>
      </div>
      <div class="kpi-item">
        <span class="kpi-label">异常</span>
        <strong class="kpi-value mono">{{ kpi.exceptions }}</strong>
        <span class="kpi-note">P0–P3 分级处置</span>
      </div>
      <div class="kpi-item">
        <span class="kpi-label">待批</span>
        <strong class="kpi-value mono">{{ kpi.approvals_pending }}</strong>
        <span class="kpi-note">L2 / L3 人工门禁</span>
      </div>
      <div class="kpi-item">
        <span class="kpi-label">补偿</span>
        <strong class="kpi-value mono">{{ kpi.compensations }}</strong>
        <span class="kpi-note">已登记 trace</span>
      </div>
    </section>

    <StatusBoard :snapshot="snapshot" :integrations="integrations" />

    <InsightBoard :analytics="snapshot.analytics" />

    <div class="overview-grid">
      <section id="agents" class="panel">
        <header class="panel-head">
          <div>
            <p class="panel-kicker">Agent 调度</p>
            <h2>
              领域 Agent
              <span v-if="ui.selectedAgentId" class="filter-note">
                · 已筛选 {{ ui.selectedAgentId }}
              </span>
            </h2>
          </div>
          <button
            v-if="ui.selectedAgentId"
            class="text-button"
            type="button"
            @click="ui.setAgentFilter(null)"
          >
            清除筛选
          </button>
        </header>
        <ul class="agent-rows">
          <li v-for="agent in agents" :key="agent.id" class="agent-row">
            <StatusDot :status="agent.status" show-label />
            <div class="agent-row-main">
              <strong>{{ agent.name }}</strong>
              <span>{{ agent.role }}</span>
              <p>{{ agent.current_task }}</p>
            </div>
            <RiskBadge :risk="agent.risk" />
            <span class="agent-state-label">{{ agent.status_label }}</span>
          </li>
        </ul>
      </section>

      <section class="panel">
        <header class="panel-head">
          <div>
            <p class="panel-kicker">审批案</p>
            <h2>待批 {{ pendingApprovals.length }} 件</h2>
          </div>
          <RouterLink class="text-link" to="/dispatch/approvals">
            全部审批 →
          </RouterLink>
        </header>
        <ul class="compact-list">
          <li v-for="approval in pendingApprovals" :key="approval.id">
            <RiskBadge :risk="approval.risk" />
            <span class="compact-main">{{ approval.title }}</span>
            <span class="compact-meta">{{ approval.stage_id }}</span>
          </li>
          <li v-if="pendingApprovals.length === 0" class="empty-row">
            审批已清 · 进入执行
          </li>
        </ul>
      </section>

      <section class="panel">
        <header class="panel-head">
          <div>
            <p class="panel-kicker">异常簿</p>
            <h2>{{ snapshot.exceptions.length }} 条异常</h2>
          </div>
          <RouterLink class="text-link" to="/dispatch/exceptions">
            全部异常 →
          </RouterLink>
        </header>
        <ul class="compact-list">
          <li
            v-for="exception in snapshot.exceptions.slice(0, 4)"
            :key="exception.id"
          >
            <span class="priority-code" :class="`priority-code--${exception.priority.toLowerCase()}`">
              {{ exception.priority }}
            </span>
            <span class="compact-main">{{ exception.title }}</span>
            <span class="compact-meta">{{ exception.stage_id }}</span>
          </li>
        </ul>
      </section>

      <section class="panel" id="trace">
        <header class="panel-head">
          <div>
            <p class="panel-kicker">审计</p>
            <h2>Trace 时间线</h2>
          </div>
          <span class="panel-note">只读</span>
        </header>
        <TraceTimeline :events="snapshot.trace" />
      </section>
    </div>
  </div>
</template>
