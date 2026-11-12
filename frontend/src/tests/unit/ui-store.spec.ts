import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUiStore } from '@/stores/ui'

describe('ui store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('toggles the mobile drawer', () => {
    const ui = useUiStore()

    expect(ui.sidebarOpen).toBe(false)
    ui.toggleSidebar()
    expect(ui.sidebarOpen).toBe(true)
    ui.closeSidebar()
    expect(ui.sidebarOpen).toBe(false)
  })

  it('expands a stage and remembers it', () => {
    const ui = useUiStore()

    ui.rememberStage('order')
    expect(ui.isStageExpanded('order')).toBe(true)
    expect(ui.lastStageId).toBe('order')

    ui.toggleStage('order')
    expect(ui.isStageExpanded('order')).toBe(false)
  })

  it('filters agents and priorities without duplicating server state', () => {
    const ui = useUiStore()

    ui.setAgentFilter('order')
    ui.setPriorityFilter('P0')

    expect(ui.selectedAgentId).toBe('order')
    expect(ui.selectedPriority).toBe('P0')
  })
})
