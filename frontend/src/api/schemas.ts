import { z } from 'zod'

/** 阶段/链路状态值；后端枚举变更时前端类型检查会先失败。 */
export const StageStatusSchema = z.enum(['done', 'running', 'alert', 'waiting'])
export const RiskSchema = z.enum(['L0', 'L1', 'L2', 'L3'])
export const PrioritySchema = z.enum(['P0', 'P1', 'P2', 'P3'])
export const ArtifactKindSchema = z.enum([
  'json',
  'csv',
  'markdown',
  'image',
  'video',
  'pdf',
  'other',
])
export const ApprovalStatusSchema = z.enum(['pending', 'approved', 'rejected'])

export const StepSchema = z.object({
  id: z.string(),
  stage: z.string(),
  name: z.string(),
  capability: z.string(),
  risk: RiskSchema,
  status: z.enum(['pending', 'running', 'succeeded', 'failed', 'skipped']),
  artifact: z.string().nullable(),
})

export const PlanSchema = z.object({
  id: z.string(),
  goal_id: z.string(),
  approval_ids: z.array(z.string()),
  risk: RiskSchema,
  created_at: z.string(),
  steps: z.array(StepSchema),
})

export const GoalSchema = z.object({
  id: z.string(),
  instruction: z.string(),
  store: z.string(),
  market: z.string(),
  target_gmv: z.number(),
  budget: z.number(),
  roas_target: z.number(),
})

export const KpiSchema = z.object({
  gmv_target: z.number(),
  exceptions: z.number(),
  approvals_pending: z.number(),
  compensations: z.number(),
})

export const ChainSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: StageStatusSchema,
  meta: z.string(),
})

export const AgentSchema = z.object({
  id: z.string(),
  name: z.string(),
  role: z.string(),
  capabilities: z.array(z.string()),
  risk: RiskSchema,
  status: z.enum(['idle', 'running', 'waiting', 'done', 'error']),
  status_label: z.string(),
  current_task: z.string(),
})

export const ArtifactSchema = z.object({
  name: z.string(),
  kind: ArtifactKindSchema,
  uri: z.string(),
  description: z.string(),
})

export const StageSourceSchema = z.object({
  platform: z.string(),
  shop_id: z.string(),
  adapter: z.string(),
  synced_at: z.string(),
  schema_version: z.string(),
})

export const StageResultSchema = z.object({
  stage_id: z.string(),
  agent_id: z.string(),
  status: StageStatusSchema,
  summary: z.string().min(1),
  artifacts: z.array(ArtifactSchema),
  metrics: z.record(z.union([z.string(), z.number()])),
  evidence: z.array(z.string()),
  source: StageSourceSchema,
  at: z.string(),
})

export const StageStepSchema = z.object({
  id: z.string(),
  name: z.string(),
})

export const StageDefinitionSchema = z.object({
  id: z.string(),
  order_label: z.string(),
  name: z.string(),
  owner: z.string(),
  risk: RiskSchema,
  actions: z.array(z.string()),
  failures: z.array(z.string()),
  ai: z.array(z.string()),
  metrics: z.array(z.string()),
  steps: z.array(StageStepSchema),
})

export const ApprovalSchema = z.object({
  id: z.string(),
  title: z.string(),
  action: z.string(),
  risk: RiskSchema,
  owner: z.string(),
  impact: z.string(),
  recommended: z.enum(['approve', 'reject']).nullable(),
  status: ApprovalStatusSchema,
  stamp: z.enum(['准', '驳']).nullable(),
  actor: z.string().nullable(),
  decided_at: z.string().nullable(),
  stage_id: z.string(),
})

export const PlaybookPhaseSchema = z.object({
  label: z.string(),
  steps: z.array(z.string()),
})

export const PlaybookSchema = z.object({
  trigger: z.string(),
  phases: z.array(PlaybookPhaseSchema),
  automation: z.string(),
})

export const ExceptionSchema = z.object({
  id: z.string(),
  title: z.string(),
  priority: PrioritySchema,
  li: z.string(),
  sla: z.string(),
  owner: z.string(),
  count: z.string(),
  playbook: PlaybookSchema,
  stage_id: z.string(),
})

export const TraceSchema = z.object({
  at: z.string(),
  title: z.string(),
  detail: z.string(),
})

export const NavigationSchema = z.object({
  id: z.string(),
  order_label: z.string(),
  name: z.string(),
  status: StageStatusSchema,
  meta: z.string(),
  approval_count: z.number(),
  exception_count: z.number(),
  steps: z.array(StageStepSchema),
})

export const ApprovalProgressSchema = z.object({
  total: z.number(),
  pending: z.number(),
  approved: z.number(),
  rejected: z.number(),
  decided_percent: z.number(),
  l2_total: z.number(),
  l3_total: z.number(),
})

export const StatusSummarySchema = z.object({
  chain: z.record(z.number()),
  agents: z.record(z.number()),
  approvals: ApprovalProgressSchema,
  exceptions: z.record(z.number()),
})

export const SalesPointSchema = z.object({
  date: z.string(),
  amount_usd: z.number(),
  target_usd: z.number(),
})

export const SalesAnalyticsSchema = z.object({
  points: z.array(SalesPointSchema),
  total_usd: z.number(),
  target_usd: z.number(),
  daily_target_usd: z.number(),
})

export const AgentUsageSchema = z.object({
  agent_id: z.string(),
  name: z.string(),
  runs: z.number(),
  success_rate: z.number(),
  avg_duration_ms: z.number(),
})

export const ResultDeliveryStageSchema = z.object({
  stage_id: z.string(),
  name: z.string(),
  status: StageStatusSchema,
  artifact_count: z.number(),
  evidence_count: z.number(),
})

export const ResultDeliverySchema = z.object({
  stages: z.array(ResultDeliveryStageSchema),
  total_results: z.number(),
  artifact_count: z.number(),
  evidence_count: z.number(),
  alert_stages: z.number(),
})

export const AnalyticsSchema = z.object({
  source: z.string(),
  sales: SalesAnalyticsSchema,
  agent_usage: z.array(AgentUsageSchema),
  results: ResultDeliverySchema,
})

export const SnapshotSchema = z.object({
  goal: GoalSchema,
  kpis: KpiSchema,
  flow_note: z.string(),
  plan: PlanSchema,
  chain: z.array(ChainSchema),
  agents: z.array(AgentSchema),
  approvals: z.record(ApprovalSchema),
  exceptions: z.array(ExceptionSchema),
  trace: z.array(TraceSchema),
  navigation: z.array(NavigationSchema),
  status_summary: StatusSummarySchema,
  approval_progress: ApprovalProgressSchema,
  analytics: AnalyticsSchema,
})

export const StageDetailSchema = StageDefinitionSchema.extend({
  status: StageStatusSchema,
  meta: z.string(),
  result: StageResultSchema.nullable(),
  approvals: z.array(ApprovalSchema),
  exceptions: z.array(ExceptionSchema),
})

export const IntegrationPlatformSchema = z.object({
  platform: z.string(),
  shop_id: z.string(),
  name: z.string(),
  status: z.enum(['connected', 'mock', 'degraded', 'disconnected']),
  mode: z.enum(['mock', 'live']),
  capabilities: z.array(z.string()),
  last_sync_at: z.string().nullable(),
  freshness: z.enum(['fresh', 'stale', 'unknown']),
  warnings: z.array(z.string()),
})

export const IntegrationsSchema = z.object({
  default_platform: z.string(),
  platforms: z.array(IntegrationPlatformSchema),
})

export const VerificationSchema = z.object({
  passed: z.boolean(),
  checks: z.array(z.string()),
  vetoed: z.array(z.string()),
})

export const ReportSchema = z.object({
  summary: z.string(),
  verification: VerificationSchema,
  steps: z.array(StepSchema),
  events: z.array(TraceSchema),
  approvals: z.array(ApprovalSchema),
})

export const DecisionResponseSchema = z.object({
  approval: ApprovalSchema,
  snapshot: SnapshotSchema,
})

export const DemoResponseSchema = z.object({
  report: ReportSchema,
  snapshot: SnapshotSchema,
})

export type Snapshot = z.infer<typeof SnapshotSchema>
export type Analytics = z.infer<typeof AnalyticsSchema>
export type AgentUsage = z.infer<typeof AgentUsageSchema>
export type SalesAnalytics = z.infer<typeof SalesAnalyticsSchema>
export type SalesPoint = z.infer<typeof SalesPointSchema>
export type ResultDelivery = z.infer<typeof ResultDeliverySchema>
export type ResultDeliveryStage = z.infer<typeof ResultDeliveryStageSchema>
export type StageDetail = z.infer<typeof StageDetailSchema>
export type StageResult = z.infer<typeof StageResultSchema>
export type StageNavigation = z.infer<typeof NavigationSchema>
export type Approval = z.infer<typeof ApprovalSchema>
export type ExceptionCase = z.infer<typeof ExceptionSchema>
export type AgentCard = z.infer<typeof AgentSchema>
export type IntegrationsResponse = z.infer<typeof IntegrationsSchema>
export type IntegrationPlatform = z.infer<typeof IntegrationPlatformSchema>
export type ApprovalProgress = z.infer<typeof ApprovalProgressSchema>
export type StatusSummary = z.infer<typeof StatusSummarySchema>
export type TraceEvent = z.infer<typeof TraceSchema>
export type Report = z.infer<typeof ReportSchema>
export type StageStatus = z.infer<typeof StageStatusSchema>
export type Priority = z.infer<typeof PrioritySchema>
