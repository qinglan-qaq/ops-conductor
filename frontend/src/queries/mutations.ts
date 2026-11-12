import { useMutation, useQueryClient } from '@tanstack/vue-query'
import {
  createGoal,
  decideApproval,
  resetApprovals,
  resetDispatch,
  runDemo,
} from '@/api/dispatch'

function useDispatchInvalidation() {
  const queryClient = useQueryClient()

  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['dispatch', 'snapshot'] }),
      queryClient.invalidateQueries({ queryKey: ['dispatch', 'stage'] }),
    ])
  }
}

/** 审批裁决；成功后失效快照与全部阶段详情，避免显示旧审批。 */
export function useDecisionMutation() {
  const invalidate = useDispatchInvalidation()
  return useMutation({
    mutationFn: (variables: {
      approvalId: string
      decision: 'approve' | 'reject'
      actor?: string
    }) =>
      decideApproval(
        variables.approvalId,
        variables.decision,
        variables.actor,
      ),
    onSuccess: invalidate,
  })
}

/** 目标创建会重建种子状态，需同时刷新快照与阶段缓存。 */
export function useGoalMutation() {
  const invalidate = useDispatchInvalidation()
  return useMutation({
    mutationFn: (instruction: string) => createGoal(instruction),
    onSuccess: invalidate,
  })
}

/** 审批重置；只影响审批与阶段上下文。 */
export function useResetApprovalsMutation() {
  const invalidate = useDispatchInvalidation()
  return useMutation({
    mutationFn: resetApprovals,
    onSuccess: invalidate,
  })
}

/** 全量恢复 Demo 种子。 */
export function useResetDispatchMutation() {
  const invalidate = useDispatchInvalidation()
  return useMutation({
    mutationFn: resetDispatch,
    onSuccess: invalidate,
  })
}

/** Demo 编排是只读投影，不失效审批或阶段缓存。 */
export function useDemoMutation() {
  return useMutation({
    mutationFn: runDemo,
  })
}
