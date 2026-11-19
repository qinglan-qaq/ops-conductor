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
  credential_status: z.enum(['not_required', 'configured', 'missing']),
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

export const RunStatusSchema = z.enum(['running', 'succeeded', 'failed'])
export const RunModeSchema = z.enum(['demo', 'live'])
export const RunStepStatusSchema = z.enum([
  'pending',
  'running',
  'succeeded',
  'failed',
  'skipped',
])
export const RunEventKindSchema = z.enum([
  'run_started',
  'agent_started',
  'tool_called',
  'step_completed',
  'handoff',
  'approval_requested',
  'approval_decided',
  'verification_passed',
  'compensation_triggered',
  'rpa_executed',
  'reconciliation_found',
  'report_generated',
  'run_completed',
])

export const RunToolCallSchema = z.object({
  tool: z.string(),
  params: z.record(z.unknown()),
  result: z.record(z.unknown()),
  status: z.string(),
  duration_ms: z.number(),
})

export const RunStepSchema = z.object({
  index: z.number(),
  id: z.string(),
  stage: z.string(),
  name: z.string(),
  agent_id: z.string(),
  capability: z.string(),
  risk: RiskSchema,
  status: RunStepStatusSchema,
  summary: z.string(),
  artifact: z.string().nullable(),
  tool_calls: z.array(RunToolCallSchema),
  approval_id: z.string().nullable(),
  duration_ms: z.number(),
  error: z.string().nullable(),
})

export const RunAgentSchema = z.object({
  id: z.string(),
  name: z.string(),
  role: z.string(),
  risk: RiskSchema,
  capabilities: z.array(z.string()),
  step_ids: z.array(z.string()),
})

export const RunEventSchema = z.object({
  seq: z.number(),
  kind: RunEventKindSchema,
  at: z.string(),
  step_id: z.string().nullable(),
  agent_id: z.string().nullable(),
  gate_id: z.string().nullable(),
  title: z.string(),
  detail: z.string(),
})

export const RunGateSchema = z.object({
  id: z.string(),
  step_id: z.string(),
  stage: z.string(),
  title: z.string(),
  action: z.string(),
  risk: RiskSchema,
  owner: z.string(),
  impact: z.string(),
  recommended: z.enum(['approve', 'reject']).nullable(),
  status: ApprovalStatusSchema,
  decision: z.enum(['approve', 'reject']).nullable(),
  actor: z.string().nullable(),
  decided_at: z.string().nullable(),
})

export const RunHandoffSchema = z.object({
  event_seq: z.number(),
  from_agent_id: z.string(),
  to_agent_id: z.string(),
  from_step_id: z.string(),
  to_step_id: z.string(),
  artifact: z.string(),
  note: z.string(),
})

export const RunArtifactSchema = z.object({
  name: z.string(),
  kind: ArtifactKindSchema,
  uri: z.string(),
  step_id: z.string(),
  agent_id: z.string(),
  description: z.string(),
})

export const RunMetricsSchema = z.object({
  step_count: z.number(),
  succeeded_steps: z.number(),
  failed_steps: z.number(),
  agent_count: z.number(),
  handoff_count: z.number(),
  gate_count: z.number(),
  approved_gates: z.number(),
  rejected_gates: z.number(),
  artifact_count: z.number(),
  compensation_count: z.number(),
  reconciliation_count: z.number(),
  duration_ms: z.number(),
})

export const RunSchema = z.object({
  id: z.string(),
  goal: GoalSchema,
  plan_id: z.string(),
  status: RunStatusSchema,
  mode: RunModeSchema,
  started_at: z.string(),
  finished_at: z.string(),
  summary: z.string(),
  steps: z.array(RunStepSchema),
  agents: z.array(RunAgentSchema),
  events: z.array(RunEventSchema),
  gates: z.array(RunGateSchema),
  handoffs: z.array(RunHandoffSchema),
  artifacts: z.array(RunArtifactSchema),
  verification: VerificationSchema,
  metrics: RunMetricsSchema,
})

export const RunListItemSchema = z.object({
  id: z.string(),
  status: RunStatusSchema,
  goal_instruction: z.string(),
  started_at: z.string(),
  step_count: z.number(),
  gate_count: z.number(),
  summary: z.string(),
})

export const RunListSchema = z.object({
  runs: z.array(RunListItemSchema),
})

export type Run = z.infer<typeof RunSchema>
export type RunStep = z.infer<typeof RunStepSchema>
export type RunAgent = z.infer<typeof RunAgentSchema>
export type RunEvent = z.infer<typeof RunEventSchema>
export type RunGate = z.infer<typeof RunGateSchema>
export type RunHandoff = z.infer<typeof RunHandoffSchema>
export type RunArtifact = z.infer<typeof RunArtifactSchema>
export type RunMetrics = z.infer<typeof RunMetricsSchema>
export type RunListItem = z.infer<typeof RunListItemSchema>
export type RunList = z.infer<typeof RunListSchema>
export type RunEventKind = z.infer<typeof RunEventKindSchema>
export type RunStatus = z.infer<typeof RunStatusSchema>
export type RunStepStatus = z.infer<typeof RunStepStatusSchema>
