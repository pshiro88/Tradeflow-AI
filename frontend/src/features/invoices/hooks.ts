import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as invoiceApi from '@/services/invoices'
import type { InvoiceCreatePayload, InvoiceListParams, InvoicePayload } from '@/types/invoice'

export const invoiceKeys = {
  all: ['invoices'] as const,
  list: (params: InvoiceListParams) => ['invoices', 'list', params] as const,
  detail: (id: string) => ['invoices', 'detail', id] as const,
  exporters: ['invoices', 'exporters'] as const,
  buyers: ['invoices', 'buyers'] as const,
}

export function useInvoices(params: InvoiceListParams) {
  // Keep the previous page on screen while the next one loads (no flicker when filtering or paging).
  return useQuery({
    queryKey: invoiceKeys.list(params),
    queryFn: () => invoiceApi.listInvoices(params),
    placeholderData: keepPreviousData,
  })
}

export function useInvoice(id: string) {
  return useQuery({ queryKey: invoiceKeys.detail(id), queryFn: () => invoiceApi.getInvoice(id) })
}

export function useExporters() {
  return useQuery({ queryKey: invoiceKeys.exporters, queryFn: invoiceApi.listExporters, staleTime: 5 * 60_000 })
}

export function useBuyers() {
  return useQuery({ queryKey: invoiceKeys.buyers, queryFn: invoiceApi.listBuyers, staleTime: 60_000 })
}

export function useCreateInvoice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: InvoiceCreatePayload) => invoiceApi.createInvoice(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: invoiceKeys.all }),
  })
}

export function useUpdateInvoice(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: InvoicePayload) => invoiceApi.updateInvoice(id, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: invoiceKeys.all }),
  })
}

export function useChangeInvoiceStatus(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (status: 'OPEN' | 'CANCELLED') => invoiceApi.changeInvoiceStatus(id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: invoiceKeys.all }),
  })
}
