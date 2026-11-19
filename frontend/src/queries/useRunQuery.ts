import type { Ref } from 'vue'
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getRun } from '@/api/dispatch'

export function runQueryKey(runId: string) {
  return ['dispatch', 'run', runId] as const
}

/** 按路由参数读取 Run 详情；切换 Run 时自动取消过期请求。 */
export function useRunQuery(runId: Ref<string | null>) {
  return useQuery({
    queryKey: computed(() => ['dispatch', 'run', runId.value ?? '']),
    queryFn: ({ signal }) => {
      if (!runId.value) {
        throw new Error('run id is required')
      }
      return getRun(runId.value, signal)
    },
    enabled: computed(() => Boolean(runId.value)),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
