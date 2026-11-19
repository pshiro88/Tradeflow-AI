import { api } from '@/lib/api'
import type { Page } from '@/types/common'
import type {
  InvoiceCreatePayload,
  InvoiceDetail,
  InvoiceListItem,
  InvoiceListParams,
  InvoicePayload,
  Party,
} from '@/types/invoice'

export async function listInvoices(params: InvoiceListParams): Promise<Page<InvoiceListItem>> {
  const { data } = await api.get<Page<InvoiceListItem>>('/invoices', { params })
  return data
}

export async function getInvoice(id: string): Promise<InvoiceDetail> {
  const { data } = await api.get<InvoiceDetail>(`/invoices/${id}`)
  return data
}

export async function createInvoice(payload: InvoiceCreatePayload): Promise<InvoiceDetail> {
  const { data } = await api.post<InvoiceDetail>('/invoices', payload)
  return data
}

export async function updateInvoice(id: string, payload: InvoicePayload): Promise<InvoiceDetail> {
  const { data } = await api.put<InvoiceDetail>(`/invoices/${id}`, payload)
  return data
}

export async function changeInvoiceStatus(id: string, status: 'OPEN' | 'CANCELLED'): Promise<InvoiceDetail> {
  const { data } = await api.patch<InvoiceDetail>(`/invoices/${id}/status`, { status })
  return data
}

export async function listExporters(): Promise<Party[]> {
  const { data } = await api.get<Party[]>('/invoices/exporters')
  return data
}

export async function listBuyers(): Promise<Party[]> {
  const { data } = await api.get<Party[]>('/invoices/buyers')
  return data
}
