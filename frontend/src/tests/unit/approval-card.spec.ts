import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ApprovalCard from '@/features/approvals/ApprovalCard.vue'
import { fallbackSnapshot } from '@/api/fixtures'

describe('ApprovalCard', () => {
  it('shows the pending seal and emits approve/reject', async () => {
    const approval = fallbackSnapshot.approvals.budget

    const wrapper = mount(ApprovalCard, {
      props: { approval, busy: false },
    })

    expect(wrapper.text()).toContain('待')
    expect(wrapper.text()).toContain('建议不自动执行')

    await wrapper.get('button[aria-label^="批准"]').trigger('click')
    expect(wrapper.emitted('decide')?.[0]).toEqual(['budget', 'approve'])

    await wrapper.get('button[aria-label^="驳回"]').trigger('click')
    expect(wrapper.emitted('decide')?.[1]).toEqual(['budget', 'reject'])
  })

  it('hides action buttons after a decision', () => {
    const approval = {
      ...fallbackSnapshot.approvals.budget,
      status: 'approved' as const,
      stamp: '准' as const,
      actor: '财务小财',
      decided_at: '11:22',
    }

    const wrapper = mount(ApprovalCard, {
      props: { approval, busy: false },
    })

    expect(wrapper.findAll('button')).toHaveLength(0)
    expect(wrapper.text()).toContain('准')
    expect(wrapper.text()).toContain('财务小财')
  })
})
