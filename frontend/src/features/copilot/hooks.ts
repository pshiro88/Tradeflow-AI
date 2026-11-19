import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as aiApi from '@/services/ai'

export const aiKeys = {
  history: ['ai', 'history'] as const,
  suggestions: ['ai', 'suggestions'] as const,
  status: ['ai', 'status'] as const,
}

export function useAIStatus() {
  // The model can come and go; re-check now and then so the banner stays truthful.
  return useQuery({ queryKey: aiKeys.status, queryFn: aiApi.getAIStatus, refetchInterval: 60_000, retry: false })
}

export function useSuggestions() {
  return useQuery({ queryKey: aiKeys.suggestions, queryFn: aiApi.getSuggestions, staleTime: Infinity })
}

export function useHistory() {
  return useQuery({ queryKey: aiKeys.history, queryFn: () => aiApi.getHistory(15) })
}

export function useChat() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (message: string) => aiApi.chat(message),
    onSettled: () => queryClient.invalidateQueries({ queryKey: aiKeys.history }),
  })
}

export function useExplainDiscrepancy() {
  return useMutation({ mutationFn: (reconciliationId: string) => aiApi.explainDiscrepancy(reconciliationId) })
}
