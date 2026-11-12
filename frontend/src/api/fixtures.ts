import raw from './fixtures.json'
import {
  IntegrationsSchema,
  SnapshotSchema,
  StageDetailSchema,
  type IntegrationsResponse,
  type Snapshot,
  type StageDetail,
} from './schemas'

/**
 * 离线 fixture 由 `scripts/export_dispatch_fixtures.py` 从后端种子导出。
 * 仅用于 API 不可用时展示「离线数据」，不得伪装成成功响应。
 */
export const fallbackSnapshot: Snapshot = SnapshotSchema.parse(raw.snapshot)

export const fallbackStageDetails: Record<string, StageDetail> = Object.fromEntries(
  Object.entries(raw.stages).map(([stageId, detail]) => [
    stageId,
    StageDetailSchema.parse(detail),
  ]),
)

export const fallbackIntegrations: IntegrationsResponse =
  IntegrationsSchema.parse(raw.integrations)
