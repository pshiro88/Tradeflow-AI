import { api } from '@/lib/api'
import type { Page } from '@/types/common'
import type { ImportBatch, ImportBatchDetail, Payment, PaymentListParams } from '@/types/payment'

export async function listPayments(params: PaymentListParams): Promise<Page<Payment>> {
  const { data } = await api.get<Page<Payment>>('/payments', { params })
  return data
}

export async function importPayments(file: File): Promise<ImportBatchDetail> {
  const form = new FormData()
  form.append('file', file)
  // Let the browser set the multipart boundary; the JSON default header would break the upload.
  const { data } = await api.post<ImportBatchDetail>('/payments/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function listImports(limit = 5): Promise<ImportBatch[]> {
  const { data } = await api.get<ImportBatch[]>('/payments/imports', { params: { limit } })
  return data
}

export async function downloadImportErrorReport(batchId: string): Promise<Blob> {
  const { data } = await api.get<Blob>(`/payments/imports/${batchId}/errors.csv`, { responseType: 'blob' })
  return data
}
