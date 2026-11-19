import { api } from '@/lib/api'
import type { Page } from '@/types/common'
import type {
  ApprovePayload,
  EligibleInvoice,
  ReconciliationDetail,
  ReconciliationItem,
  ReconciliationListParams,
  RunSummary,
  StatusSummary,
} from '@/types/reconciliation'

export async function runReconciliation(): Promise<RunSummary> {
  const { data } = await api.post<RunSummary>('/reconciliation/run')
  return data
}

export async function getSummary(): Promise<StatusSummary> {
  const { data } = await api.get<StatusSummary>('/reconciliation/summary')
  return data
}

export async function listResults(params: ReconciliationListParams): Promise<Page<ReconciliationItem>> {
  const { data } = await api.get<Page<ReconciliationItem>>('/reconciliation', { params })
  return data
}

export async function getResult(id: string): Promise<ReconciliationDetail> {
  const { data } = await api.get<ReconciliationDetail>(`/reconciliation/${id}`)
  return data
}

export async function listEligibleInvoices(id: string): Promise<EligibleInvoice[]> {
  const { data } = await api.get<EligibleInvoice[]>(`/reconciliation/${id}/eligible-invoices`)
  return data
}

export async function approveResult(id: string, payload: ApprovePayload): Promise<ReconciliationDetail> {
  const { data } = await api.post<ReconciliationDetail>(`/reconciliation/${id}/approve`, payload)
  return data
}

export async function rejectResult(id: string, note?: string): Promise<ReconciliationDetail> {
  const { data } = await api.post<ReconciliationDetail>(`/reconciliation/${id}/reject`, { note })
  return data
}
