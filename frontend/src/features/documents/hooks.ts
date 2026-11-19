import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as documentApi from '@/services/documents'
import type { DocumentListParams, DocumentType, VerifyPayload } from '@/types/document'

export const documentKeys = {
  all: ['documents'] as const,
  list: (params: DocumentListParams) => ['documents', 'list', params] as const,
  detail: (id: string) => ['documents', 'detail', id] as const,
}

export function useDocuments(params: DocumentListParams) {
  return useQuery({
    queryKey: documentKeys.list(params),
    queryFn: () => documentApi.listDocuments(params),
    placeholderData: keepPreviousData,
  })
}

export function useDocument(id: string | null) {
  return useQuery({ queryKey: documentKeys.detail(id ?? ''), queryFn: () => documentApi.getDocument(id as string), enabled: !!id })
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (v: { file: File; documentType: DocumentType; invoiceId?: string }) =>
      documentApi.uploadDocument(v.file, v.documentType, v.invoiceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: documentKeys.all }),
  })
}

export function useExtractDocument(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => documentApi.extractDocument(id),
    // A failed extraction still changes the document's status (FAILED), so always refresh.
    onSettled: () => queryClient.invalidateQueries({ queryKey: documentKeys.all }),
  })
}

export function useVerifyDocument(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: VerifyPayload) => documentApi.verifyDocument(id, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: documentKeys.all }),
  })
}

export function useExplainDocument(id: string) {
  return useMutation({ mutationFn: () => documentApi.explainDocument(id) })
}
