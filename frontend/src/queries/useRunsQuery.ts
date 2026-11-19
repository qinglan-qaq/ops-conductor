import { useQuery } from '@tanstack/vue-query'
import { listRuns } from '@/api/dispatch'

export function runsQueryKey(limit = 3) {
  return ['dispatch', 'runs', limit] as const
}

/** 读取最近 Run 列表；不存在时返回空数组，不阻塞首页。 */
export function useRunsQuery(limit = 3) {
  return useQuery({
    queryKey: runsQueryKey(limit),
    queryFn: ({ signal }) => listRuns(limit, signal),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
