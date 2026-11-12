import { useQuery } from '@tanstack/vue-query'
import { getSnapshot } from '@/api/dispatch'

export const snapshotQueryKey = ['dispatch', 'snapshot'] as const

/** 读取调度台完整快照；侧栏、首页与审批共用同一缓存键。 */
export function useSnapshotQuery() {
  return useQuery({
    queryKey: snapshotQueryKey,
    queryFn: ({ signal }) => getSnapshot(signal),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
