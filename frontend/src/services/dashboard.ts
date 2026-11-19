import { api } from '@/lib/api'
import type {
  CurrencyDistribution,
  DashboardFilters,
  DashboardSummary,
  OutstandingInvoice,
  PaymentDistribution,
  PaymentTrends,
  RecentTransaction,
} from '@/types/dashboard'

export async function getSummary(params: DashboardFilters): Promise<DashboardSummary> {
  const { data } = await api.get<DashboardSummary>('/dashboard/summary', { params })
  return data
}

export async function getPaymentTrends(params: DashboardFilters & { months: number }): Promise<PaymentTrends> {
  const { data } = await api.get<PaymentTrends>('/dashboard/payment-trends', { params })
  return data
}

export async function getPaymentDistribution(params: DashboardFilters): Promise<PaymentDistribution> {
  const { data } = await api.get<PaymentDistribution>('/dashboard/payment-distribution', { params })
  return data
}

export async function getCurrencyDistribution(params: DashboardFilters): Promise<CurrencyDistribution> {
  const { data } = await api.get<CurrencyDistribution>('/dashboard/currency-distribution', { params })
  return data
}

export async function getRecentTransactions(params: DashboardFilters): Promise<RecentTransaction[]> {
  const { data } = await api.get<RecentTransaction[]>('/dashboard/recent-transactions', { params })
  return data
}

export async function getOutstandingInvoices(params: DashboardFilters): Promise<OutstandingInvoice[]> {
  const { data } = await api.get<OutstandingInvoice[]>('/dashboard/outstanding-invoices', { params })
  return data
}
