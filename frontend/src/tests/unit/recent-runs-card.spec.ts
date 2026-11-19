import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RecentRunsCard from '@/features/overview/RecentRunsCard.vue'
import type { RunListItem } from '@/api/types'

const runs: RunListItem[] = [
  {
    id: 'run-3',
    status: 'succeeded',
    goal_instruction: '本周做到 $100k GMV',
    started_at: '10:43',
    step_count: 10,
    gate_count: 3,
    summary: '10 个节点执行完成',
  },
  {
    id: 'run-2',
    status: 'succeeded',
    goal_instruction: '把退款率稳住',
    started_at: '10:30',
    step_count: 10,
    gate_count: 3,
    summary: '10 个节点执行完成',
  },
]

describe('RecentRunsCard', () => {
  it('lists recent runs and emits open', async () => {
    const wrapper = mount(RecentRunsCard, {
      props: { runs, loading: false, error: false },
    })

    expect(wrapper.findAll('[data-recent-run]')).toHaveLength(2)
    await wrapper.findAll('[data-recent-run]')[0].trigger('click')
    expect(wrapper.emitted('open')).toEqual([['run-3']])
  })

  it('shows an empty state and can start a run', async () => {
    const wrapper = mount(RecentRunsCard, {
      props: { runs: [], loading: false, error: false },
    })

    expect(wrapper.find('[data-recent-runs-empty]').exists()).toBe(true)
    const buttons = wrapper.findAll('button')
    await buttons[buttons.length - 1].trigger('click')
    expect(wrapper.emitted('start')).toHaveLength(1)
  })

  it('does not block the page when the run list fails', () => {
    const wrapper = mount(RecentRunsCard, {
      props: { runs: [], loading: false, error: true },
    })

    expect(wrapper.find('[data-recent-runs-error]').text()).toContain('暂不可用')
  })
})
