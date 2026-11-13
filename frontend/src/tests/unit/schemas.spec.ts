import { describe, expect, it } from 'vitest'
import {
  SnapshotSchema,
  StageDetailSchema,
  IntegrationsSchema,
} from '@/api/schemas'
import {
  fallbackIntegrations,
  fallbackSnapshot,
  fallbackStageDetails,
} from '@/api/fixtures'

describe('api schemas', () => {
  it('parses the exported backend fixtures', () => {
    const snapshot = SnapshotSchema.parse(fallbackSnapshot)

    expect(snapshot.navigation).toHaveLength(11)
    expect(snapshot.analytics.sales.points).toHaveLength(7)
    expect(snapshot.analytics.agent_usage).toHaveLength(8)
    expect(snapshot.analytics.results.stages).toHaveLength(10)
    expect(fallbackStageDetails.order.result?.metrics.exceptions).toBe(6)
    expect(IntegrationsSchema.parse(fallbackIntegrations).default_platform).toBe(
      'mock-nestwell-us',
    )
  })

  it('rejects a stage result with a blank summary', () => {
    const detail = structuredClone(fallbackStageDetails.order)
    if (detail.result) {
      detail.result.summary = ''
    }

    const parsed = StageDetailSchema.safeParse(detail)

    expect(parsed.success).toBe(false)
  })

  it('rejects stage metrics that are not a key-value object', () => {
    const detail = structuredClone(fallbackStageDetails.order)
    const result = detail.result as unknown as Record<string, unknown>
    result.metrics = [{ key: 'exceptions', value: 6 }]

    const parsed = StageDetailSchema.safeParse(detail)

    expect(parsed.success).toBe(false)
  })
})
