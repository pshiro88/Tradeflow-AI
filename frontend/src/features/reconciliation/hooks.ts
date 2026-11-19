import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import * as api from '@/services/reconciliation'
import type { ApprovePayload, ReconciliationListParams } from '@/types/reconciliation'

export const reconKeys = {
  all: ['reconciliation'] as const,
  summary: ['reconciliation', 'summary'] as const,
  list: (params: ReconciliationListParams) => ['reconciliation', 'list', params] as const,
  detail: (id: string) => ['reconciliation', 'detail', id] as const,
  eligible: (id: string) => ['reconciliation', 'eligible', id] as const,
}

/** Reconciling changes payment statuses and invoice balances, so refresh all of them. */
function invalidateMoneyViews(queryClient: QueryClient) {
  for (const key of ['reconciliation', 'payments', 'invoices']) {
    void queryClient.invalidateQueries({ queryKey: [key] })
  }
}

export function useReconciliationSummary() {
  return useQuery({ queryKey: reconKeys.summary, queryFn: api.getSummary })
}

export function useReconciliationResults(params: ReconciliationListParams) {
  return useQuery({
    queryKey: reconKeys.list(params),
    queryFn: () => api.listResults(params),
    placeholderData: keepPreviousData,
  })
}

export function useReconciliationDetail(id: string | null) {
  return useQuery({ queryKey: reconKeys.detail(id ?? ''), queryFn: () => api.getResult(id as string), enabled: !!id })
}

export function useEligibleInvoices(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: reconKeys.eligible(id ?? ''),
    queryFn: () => api.listEligibleInvoices(id as string),
    enabled: !!id && enabled,
  })
}

export function useRunReconciliation() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: api.runReconciliation, onSuccess: () => invalidateMoneyViews(queryClient) })
}

export function useApproveResult(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ApprovePayload) => api.approveResult(id, payload),
    onSuccess: () => invalidateMoneyViews(queryClient),
  })
}

export function useRejectResult(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (note?: string) => api.rejectResult(id, note),
    onSuccess: () => invalidateMoneyViews(queryClient),
  })
}
