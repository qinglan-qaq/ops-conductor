import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Priority } from '@/api/schemas'

/**
 * 纯客户端 UI 状态：侧栏抽屉、筛选与折叠。
 *
 * 当前路由/阶段不复制到 store，始终以 Vue Router 为准，避免出现两份
 * “当前页面”互相漂移。expandedStages 使用字符串数组以便序列化和稳定比较。
 */
export const useUiStore = defineStore('ui', () => {
  const sidebarOpen = ref(false)
  const selectedAgentId = ref<string | null>(null)
  const selectedPriority = ref<Priority | null>(null)
  const expandedStages = ref<string[]>([])
  const lastStageId = ref<string | null>(null)

  function openSidebar(): void {
    sidebarOpen.value = true
  }

  function closeSidebar(): void {
    sidebarOpen.value = false
  }

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  function isStageExpanded(stageId: string): boolean {
    return expandedStages.value.includes(stageId)
  }

  function expandStage(stageId: string): void {
    if (!isStageExpanded(stageId)) {
      expandedStages.value = [...expandedStages.value, stageId]
    }
  }

  function toggleStage(stageId: string): void {
    expandedStages.value = isStageExpanded(stageId)
      ? expandedStages.value.filter((id) => id !== stageId)
      : [...expandedStages.value, stageId]
  }

  function setAgentFilter(agentId: string | null): void {
    selectedAgentId.value = agentId
  }

  function setPriorityFilter(priority: Priority | null): void {
    selectedPriority.value = priority
  }

  function rememberStage(stageId: string): void {
    lastStageId.value = stageId
    expandStage(stageId)
  }

  return {
    sidebarOpen,
    selectedAgentId,
    selectedPriority,
    expandedStages,
    lastStageId,
    openSidebar,
    closeSidebar,
    toggleSidebar,
    isStageExpanded,
    expandStage,
    toggleStage,
    setAgentFilter,
    setPriorityFilter,
    rememberStage,
  }
})
