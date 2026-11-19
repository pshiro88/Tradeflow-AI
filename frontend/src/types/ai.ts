export interface SourceRef {
  type: 'invoice' | 'payment' | 'reconciliation' | 'document'
  label: string
  path: string
}

export interface AnswerTable {
  title: string
  columns: { key: string; label: string; align: 'left' | 'right' }[]
  rows: Record<string, string>[]
}

export interface ChatResponse {
  answer: string
  /** The deterministic wording, always provided so the AI's version can be compared with it. */
  standard_answer: string
  /** "AI" = wording written by the local model from retrieved data; "RULES" = fixed text. */
  generated_by: 'AI' | 'RULES'
  ai_note: string | null
  intent: string
  intent_method: string
  table: AnswerTable | null
  sources: SourceRef[]
  suggestions: string[]
}

export interface HistoryItem {
  id: string
  question: string
  answer: string | null
  intent: string | null
  generated_by: string | null
  status: string
  created_at: string
}

export interface AIStatus {
  available: boolean
  model: string
}

export interface DiscrepancyExplanation {
  status: string
  explanation: string
  generated_by: 'AI' | 'RULES'
  ai_note: string | null
  rule_explanation: string
  next_step: string
}
