import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '@/services/compliance'
import type { CheckPayload, ComplianceListParams } from '@/types/compliance'

export const complianceKeys = {
  all: ['compliance'] as const,
  list: (p: ComplianceListParams) => ['compliance', 'list', p] as const,
  checklist: (id: string) => ['compliance', 'checklist', id] as const,
  lifecycle: (id: string) => ['compliance', 'lifecycle', id] as const,
}

export function useComplianceList(params: ComplianceListParams) {
  return useQuery({ queryKey: complianceKeys.list(params), queryFn: () => api.listCompliance(params), placeholderData: keepPreviousData })
}

export function useChecklist(invoiceId: string | null) {
  return useQuery({ queryKey: complianceKeys.checklist(invoiceId ?? ''), queryFn: () => api.getChecklist(invoiceId as string), enabled: !!invoiceId })
}

export function useRecordCheck(invoiceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CheckPayload) => api.recordCheck(invoiceId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: complianceKeys.all }),
  })
}

/** Where an invoice stands from issue to "ready for export filing". Readable by every role. */
export function useLifecycle(invoiceId: string) {
  return useQuery({ queryKey: complianceKeys.lifecycle(invoiceId), queryFn: () => api.getLifecycle(invoiceId) })
}
