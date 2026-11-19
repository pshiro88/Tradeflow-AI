import { keepPreviousData, useQuery } from '@tanstack/react-query'

import * as api from '@/services/audit'
import type { AIAuditListParams, AuditListParams } from '@/types/audit'

export function useActivityLogs(params: AuditListParams) {
  return useQuery({ queryKey: ['audit', 'activity', params], queryFn: () => api.listActivity(params), placeholderData: keepPreviousData })
}

export function useAIRequestLogs(params: AIAuditListParams, enabled: boolean) {
  return useQuery({ queryKey: ['audit', 'ai', params], queryFn: () => api.listAIRequests(params), placeholderData: keepPreviousData, enabled })
}

export function useAuditOptions() {
  return useQuery({ queryKey: ['audit', 'options'], queryFn: api.getAuditOptions, staleTime: 30_000 })
}
