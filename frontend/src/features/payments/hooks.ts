import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as paymentApi from '@/services/payments'
import type { PaymentListParams } from '@/types/payment'

export const paymentKeys = {
  all: ['payments'] as const,
  list: (params: PaymentListParams) => ['payments', 'list', params] as const,
  imports: ['payments', 'imports'] as const,
}

export function usePayments(params: PaymentListParams) {
  return useQuery({
    queryKey: paymentKeys.list(params),
    queryFn: () => paymentApi.listPayments(params),
    placeholderData: keepPreviousData,
  })
}

export function useRecentImports() {
  return useQuery({ queryKey: paymentKeys.imports, queryFn: () => paymentApi.listImports(5) })
}

export function useImportPayments() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => paymentApi.importPayments(file),
    // New payments change the list, the import history, and (later) reconciliation and dashboard data.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: paymentKeys.all }),
  })
}
