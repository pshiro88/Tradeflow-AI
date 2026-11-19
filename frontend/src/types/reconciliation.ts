import type { ReconciliationStatus } from '@/types/payment'

export type ReviewDecision = 'NONE' | 'APPROVED' | 'REJECTED'

/** Money values are decimal strings (e.g. "6000.00"); the browser never does money arithmetic. */
export interface ReconciliationItem {
  id: string
  payment_id: string
  transaction_reference: string
  payment_reference: string | null
  sender_name: string
  currency: string
  payment_amount: string
  transaction_date: string
  invoice_id: string | null
  invoice_number: string | null
  invoice_currency: string | null
  invoice_amount: string | null
  previously_received: string | null
  allocated_amount: string
  outstanding_after: string | null
  match_method: string | null
  confidence: string | null
  status: ReconciliationStatus
  explanation: string | null
  review_decision: ReviewDecision
  needs_review: boolean
  created_at: string
}

export interface Candidate {
  invoice_id: string
  invoice_number: string
  buyer_name: string
  currency: string
  outstanding: string
  name_score: number
  reason: string
}

export interface ReconciliationDetail extends ReconciliationItem {
  candidates: Candidate[]
  review_note: string | null
  reviewed_by_name: string | null
  reviewed_at: string | null
  payment_unallocated: string
}

export interface StatusSummary {
  counts: Record<string, number>
  total: number
  needs_review: number
}

export interface RunSummary {
  processed: number
  counts: Record<string, number>
  allocations_created: number
}

export interface EligibleInvoice {
  invoice_id: string
  invoice_number: string
  buyer_name: string
  currency: string
  outstanding: string
  due_date: string
  name_score: number
  is_candidate: boolean
}

export interface ReconciliationListParams {
  page: number
  page_size: number
  status?: ReconciliationStatus
  needs_review?: boolean
  search?: string
}

export interface ApprovePayload {
  invoice_id: string
  amount?: string
  note?: string
}
