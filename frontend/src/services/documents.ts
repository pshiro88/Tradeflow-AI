import { api } from '@/lib/api'
import type { Page } from '@/types/common'
import type {
  DocumentDetail,
  DocumentExplanation,
  DocumentListItem,
  DocumentListParams,
  DocumentType,
  VerifyPayload,
} from '@/types/document'

export async function listDocuments(params: DocumentListParams): Promise<Page<DocumentListItem>> {
  const { data } = await api.get<Page<DocumentListItem>>('/documents', { params })
  return data
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  const { data } = await api.get<DocumentDetail>(`/documents/${id}`)
  return data
}

export async function uploadDocument(file: File, documentType: DocumentType, invoiceId?: string): Promise<DocumentDetail> {
  const form = new FormData()
  form.append('file', file)
  form.append('document_type', documentType)
  if (invoiceId) form.append('invoice_id', invoiceId)
  const { data } = await api.post<DocumentDetail>('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

/** Local AI extraction can take a while on a CPU, so the usual request timeout does not apply here. */
export async function extractDocument(id: string): Promise<DocumentDetail> {
  const { data } = await api.post<DocumentDetail>(`/documents/${id}/extract`, undefined, { timeout: 0 })
  return data
}

export async function verifyDocument(id: string, payload: VerifyPayload): Promise<DocumentDetail> {
  const { data } = await api.post<DocumentDetail>(`/documents/${id}/verify`, payload)
  return data
}

export async function explainDocument(id: string): Promise<DocumentExplanation> {
  const { data } = await api.post<DocumentExplanation>(`/documents/${id}/explain`, undefined, { timeout: 0 })
  return data
}
