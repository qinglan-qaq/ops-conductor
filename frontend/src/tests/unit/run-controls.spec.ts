import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunControls from '@/features/runs/RunControls.vue'

describe('RunControls', () => {
  it('renders playback controls and emits actions', async () => {
    const wrapper = mount(RunControls, {
      props: {
        status: 'paused',
        speed: 1,
        progress: 0.4,
        cursor: 20,
        total: 51,
        showAll: false,
        follow: true,
      },
    })

    expect(wrapper.find('[data-player-toggle]').text()).toBe('播放')
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuemax')).toBe('51')
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('20')

    await wrapper.find('[data-player-toggle]').trigger('click')
    await wrapper.find('[data-player-prev]').trigger('click')
    await wrapper.find('[data-player-next]').trigger('click')
    await wrapper.find('[data-player-replay]').trigger('click')
    await wrapper.find('[data-player-show-all]').trigger('click')
    await wrapper.find('[data-player-follow]').trigger('click')

    expect(wrapper.emitted('toggle')).toHaveLength(1)
    expect(wrapper.emitted('prev')).toHaveLength(1)
    expect(wrapper.emitted('next')).toHaveLength(1)
    expect(wrapper.emitted('replay')).toHaveLength(1)
    expect(wrapper.emitted('toggle-show-all')).toHaveLength(1)
    expect(wrapper.emitted('toggle-follow')).toHaveLength(1)
  })

  it('emits the selected speed', async () => {
    const wrapper = mount(RunControls, {
      props: {
        status: 'playing',
        speed: 1,
        progress: 0,
        cursor: 0,
        total: 51,
        showAll: false,
        follow: true,
      },
    })

    await wrapper.find('select').setValue('4')

    expect(wrapper.emitted('speed')).toEqual([[4]])
  })
})
