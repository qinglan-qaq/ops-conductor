import { describe, expect, it } from 'vitest'
import {
  RunListSchema,
  RunSchema,
  SnapshotSchema,
  StageDetailSchema,
  IntegrationsSchema,
} from '@/api/schemas'
import {
  fallbackIntegrations,
  fallbackSnapshot,
  fallbackStageDetails,
} from '@/api/fixtures'
import { runFixture } from '@/tests/fixtures/run'

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

  it('parses the backend run fixture', () => {
    const run = RunSchema.parse(runFixture)

    expect(run.steps).toHaveLength(10)
    expect(run.agents).toHaveLength(8)
    expect(run.events).toHaveLength(51)
    expect(run.handoffs).toHaveLength(8)
    expect(run.gates).toHaveLength(3)
    expect(run.metrics.reconciliation_count).toBe(3)
  })

  it('rejects a run event without a title', () => {
    const run = structuredClone(runFixture)
    delete (run.events[0] as unknown as Record<string, unknown>).title

    const parsed = RunSchema.safeParse(run)

    expect(parsed.success).toBe(false)
  })

  it('parses a run list payload', () => {
    const parsed = RunListSchema.parse({
      runs: [
        {
          id: 'run-1',
          status: 'succeeded',
          goal_instruction: '测试目标',
          started_at: '10:43',
          step_count: 10,
          gate_count: 3,
          summary: '10 个节点执行完成',
        },
      ],
    })

    expect(parsed.runs[0]?.id).toBe('run-1')
  })
})
