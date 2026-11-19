import { api } from '@/lib/api'
import type { AIStatus, ChatResponse, DiscrepancyExplanation, HistoryItem } from '@/types/ai'

export async function chat(message: string): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>('/ai/chat', { message }, { timeout: 0 })
  return data
}

export async function getHistory(limit = 15): Promise<HistoryItem[]> {
  const { data } = await api.get<HistoryItem[]>('/ai/history', { params: { limit } })
  return data
}

export async function getSuggestions(): Promise<string[]> {
  const { data } = await api.get<string[]>('/ai/suggestions')
  return data
}

export async function getAIStatus(): Promise<AIStatus> {
  const { data } = await api.get<AIStatus>('/ai/status')
  return data
}

export async function explainDiscrepancy(reconciliationId: string): Promise<DiscrepancyExplanation> {
  const { data } = await api.post<DiscrepancyExplanation>(
    '/ai/explain-discrepancy',
    { reconciliation_id: reconciliationId },
    { timeout: 0 },
  )
  return data
}
