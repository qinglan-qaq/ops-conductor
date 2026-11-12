import type { Ref } from 'vue'
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getStageDetail } from '@/api/dispatch'

export function stageQueryKey(stageId: string) {
  return ['dispatch', 'stage', stageId] as const
}

/** 按路由参数读取阶段详情；切换阶段时自动取消过期请求。 */
export function useStageDetailQuery(stageId: Ref<string | null>) {
  return useQuery({
    queryKey: computed(() => ['dispatch', 'stage', stageId.value ?? '']),
    queryFn: ({ signal }) => {
      if (!stageId.value) {
        throw new Error('stage id is required')
      }
      return getStageDetail(stageId.value, signal)
    },
    enabled: computed(() => Boolean(stageId.value)),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
