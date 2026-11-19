import type { DocumentFinding, DocumentType, ExtractionStatus, VerificationStatus } from '@/types/document'
import type { InvoiceStatus } from '@/types/invoice'

export interface ChecklistDocument {
  id: string
  file_name: string
  verification_status: VerificationStatus
  extraction_status: ExtractionStatus
}

export interface ChecklistItem {
  document_type: DocumentType
  label: string
  required: boolean
  requirement_note: string | null
  status: VerificationStatus
  /** Where the status comes from: an uploaded document, a person's manual review, or nothing yet. */
  source: 'DOCUMENT' | 'MANUAL' | 'NONE'
  documents: ChecklistDocument[]
  remarks: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  compared_document: string | null
  findings: DocumentFinding[]
  has_mismatch: boolean
}

export interface ChecklistSummary {
  required_total: number
  verified: number
  under_review: number
  uploaded: number
  rejected: number
  missing: number
  flagged: number
  complete: boolean
}

export interface Readiness {
  ready: boolean
  reasons: string[]
}

export interface Checklist {
  invoice_id: string
  invoice_number: string
  buyer_name: string
  invoice_status: InvoiceStatus
  items: ChecklistItem[]
  summary: ChecklistSummary
  readiness: Readiness
  disclaimer: string
}

export interface ComplianceOverviewItem {
  invoice_id: string
  invoice_number: string
  buyer_name: string
  currency: string
  invoice_status: InvoiceStatus
  due_date: string
  required_total: number
  verified: number
  missing: number
  flagged: number
  complete: boolean
  ready: boolean
}

export interface ComplianceListParams {
  page: number
  page_size: number
  search?: string
  incomplete_only?: boolean
}

export interface CheckPayload {
  document_type: DocumentType
  status: 'UNDER_REVIEW' | 'VERIFIED' | 'REJECTED'
  remarks?: string
}

export type LifecycleState = 'DONE' | 'IN_PROGRESS' | 'PENDING' | 'NOT_APPLICABLE'

export interface LifecycleStep {
  key: string
  label: string
  state: LifecycleState
  date: string | null
  detail: string
}

export interface Lifecycle {
  invoice_id: string
  steps: LifecycleStep[]
  readiness: Readiness
  note: string
}
