import { request } from './client'
import {
  DecisionResponseSchema,
  DemoResponseSchema,
  IntegrationsSchema,
  RunListSchema,
  RunSchema,
  SnapshotSchema,
  StageDetailSchema,
  type IntegrationsResponse,
  type Run,
  type RunList,
  type Snapshot,
  type StageDetail,
} from './schemas'

export function getSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  return request('/snapshot', SnapshotSchema, { signal })
}

export function getStageDetail(
  stageId: string,
  signal?: AbortSignal,
): Promise<StageDetail> {
  return request(
    `/stages/${encodeURIComponent(stageId)}`,
    StageDetailSchema,
    { signal },
  )
}

export function getIntegrations(
  signal?: AbortSignal,
): Promise<IntegrationsResponse> {
  return request('/integrations', IntegrationsSchema, { signal })
}

export function createGoal(instruction: string): Promise<Snapshot> {
  return request('/goals', SnapshotSchema, {
    method: 'POST',
    body: JSON.stringify({ instruction }),
  })
}

export function decideApproval(
  approvalId: string,
  decision: 'approve' | 'reject',
  actor = 'demo-operator',
) {
  return request(
    `/approvals/${encodeURIComponent(approvalId)}/decision`,
    DecisionResponseSchema,
    {
      method: 'POST',
      body: JSON.stringify({ decision, actor }),
    },
  )
}

export function resetApprovals(): Promise<Snapshot> {
  return request('/approvals/reset', SnapshotSchema, { method: 'POST' })
}

export function runDemo() {
  return request('/demo/run', DemoResponseSchema, { method: 'POST' })
}

export function resetDispatch(): Promise<Snapshot> {
  return request('/reset', SnapshotSchema, { method: 'POST' })
}

export function startRun(): Promise<Run> {
  return request('/runs', RunSchema, { method: 'POST' })
}

export function getRun(runId: string, signal?: AbortSignal): Promise<Run> {
  return request(`/runs/${encodeURIComponent(runId)}`, RunSchema, { signal })
}

export function getLatestRun(signal?: AbortSignal): Promise<Run> {
  return request('/runs/latest', RunSchema, { signal })
}

export function listRuns(limit = 3, signal?: AbortSignal): Promise<RunList> {
  return request(`/runs?limit=${encodeURIComponent(String(limit))}`, RunListSchema, {
    signal,
  })
}
