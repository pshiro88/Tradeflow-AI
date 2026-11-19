import { keepPreviousData, useQuery } from '@tanstack/react-query'

import * as api from '@/services/dashboard'
import type { DashboardFilters } from '@/types/dashboard'

/** An inverted date range can never match anything (the API rejects it), so no request is sent for it. */
export function isRangeValid(filters: DashboardFilters): boolean {
  return !(filters.date_from && filters.date_to && filters.date_from > filters.date_to)
}

// Hold the previous result on screen while a filter change refetches: no skeleton flash, no layout jump.
// While the range is invalid the last good figures simply stay put (the filter bar explains why).
const options = (filters: DashboardFilters) =>
  ({ placeholderData: keepPreviousData, staleTime: 15_000, enabled: isRangeValid(filters) }) as const

export function useDashboardSummary(filters: DashboardFilters) {
  return useQuery({ queryKey: ['dashboard', 'summary', filters], queryFn: () => api.getSummary(filters), ...options(filters) })
}

export function usePaymentTrends(filters: DashboardFilters, months: number) {
  return useQuery({
    queryKey: ['dashboard', 'trends', filters, months],
    queryFn: () => api.getPaymentTrends({ ...filters, months }),
    ...options(filters),
  })
}

export function usePaymentDistribution(filters: DashboardFilters) {
  return useQuery({
    queryKey: ['dashboard', 'payment-distribution', filters],
    queryFn: () => api.getPaymentDistribution(filters),
    ...options(filters),
  })
}

export function useCurrencyDistribution(filters: DashboardFilters) {
  return useQuery({
    queryKey: ['dashboard', 'currency-distribution', filters],
    queryFn: () => api.getCurrencyDistribution(filters),
    ...options(filters),
  })
}

export function useRecentTransactions(filters: DashboardFilters) {
  return useQuery({
    queryKey: ['dashboard', 'recent', filters],
    queryFn: () => api.getRecentTransactions(filters),
    ...options(filters),
  })
}

export function useOutstandingInvoices(filters: DashboardFilters) {
  return useQuery({
    queryKey: ['dashboard', 'outstanding', filters],
    queryFn: () => api.getOutstandingInvoices(filters),
    ...options(filters),
  })
}
