import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunSummary from '@/features/runs/RunSummary.vue'
import { runFixture } from '@/tests/fixtures/run'

describe('RunSummary', () => {
  it('shows the run totals and verification verdict', () => {
    const wrapper = mount(RunSummary, { props: { run: runFixture } })
    const text = wrapper.text()

    expect(text).toContain('10 步')
    expect(text).toContain('8 Agent')
    expect(text).toContain('8 次交接')
    expect(text).toContain('3 个门禁')
    expect(text).toContain('1 次补偿')
    expect(text).toContain('3 笔对账差异')
    expect(text).toContain('Verifier 通过')
    expect(text).toContain('margin 6.8% < 15%')
  })
})
