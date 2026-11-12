import { useQuery } from '@tanstack/vue-query'
import { getIntegrations } from '@/api/dispatch'

export const integrationsQueryKey = ['dispatch', 'integrations'] as const

/** 读取平台能力与集成健康；Demo 不开启轮询，避免无意义请求。 */
export function useIntegrationsQuery() {
  return useQuery({
    queryKey: integrationsQueryKey,
    queryFn: ({ signal }) => getIntegrations(signal),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
