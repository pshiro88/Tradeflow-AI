import { api } from '@/lib/api'
import type { Page } from '@/types/common'
import type { CheckPayload, Checklist, ComplianceListParams, ComplianceOverviewItem, Lifecycle } from '@/types/compliance'

export async function listCompliance(params: ComplianceListParams): Promise<Page<ComplianceOverviewItem>> {
  const { data } = await api.get<Page<ComplianceOverviewItem>>('/compliance', { params })
  return data
}

export async function getChecklist(invoiceId: string): Promise<Checklist> {
  const { data } = await api.get<Checklist>(`/compliance/${invoiceId}`)
  return data
}

export async function recordCheck(invoiceId: string, payload: CheckPayload): Promise<Checklist> {
  const { data } = await api.post<Checklist>(`/compliance/${invoiceId}/checks`, payload)
  return data
}

export async function getLifecycle(invoiceId: string): Promise<Lifecycle> {
  const { data } = await api.get<Lifecycle>(`/invoices/${invoiceId}/lifecycle`)
  return data
}
