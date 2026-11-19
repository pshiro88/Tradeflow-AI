export const DOCUMENT_TYPES = [
  'COMMERCIAL_INVOICE',
  'PACKING_LIST',
  'SHIPPING_BILL',
  'BILL_OF_LADING',
  'REMITTANCE_ADVICE',
  'OTHER',
] as const
export type DocumentType = (typeof DOCUMENT_TYPES)[number]

export type ExtractionStatus = 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED'
export type VerificationStatus = 'NOT_UPLOADED' | 'UPLOADED' | 'UNDER_REVIEW' | 'VERIFIED' | 'REJECTED'

/** How trustworthy an extracted value is, judged by checking it against the document text. */
export type FieldQuality = 'FOUND_IN_TEXT' | 'NOT_FOUND_IN_TEXT' | 'INFERRED' | 'MISSING'

export const FIELD_KEYS = [
  'document_type',
  'invoice_number',
  'exporter_name',
  'buyer_name',
  'buyer_country',
  'currency',
  'invoice_amount',
  'invoice_date',
  'due_date',
] as const
export type FieldKey = (typeof FIELD_KEYS)[number]

/** Money and dates are strings, never JS numbers or Dates. */
export type FieldValues = Record<FieldKey, string | null>

export interface ExtractionInfo {
  fields: FieldValues
  quality: Record<FieldKey, FieldQuality>
  /** The model's own estimate. NOT a probability and not proof of correctness. */
  llm_confidence: Partial<Record<FieldKey, number>>
  issues: { field: string; message: string }[]
  model: string
  truncated: boolean
  page_count: number
}

export interface ConfirmationInfo {
  fields: Partial<FieldValues>
  decision: 'VERIFIED' | 'REJECTED'
  note: string | null
  by: string | null
  at: string | null
}

export interface DocumentListItem {
  id: string
  invoice_id: string | null
  invoice_number: string | null
  file_name: string
  document_type: DocumentType
  extraction_status: ExtractionStatus
  verification_status: VerificationStatus
  uploaded_by_name: string | null
  created_at: string
}

export interface DocumentDetail extends DocumentListItem {
  extraction: ExtractionInfo | null
  confirmation: ConfirmationInfo | null
}

export interface DocumentFinding {
  field: string
  label: string
  status: 'MATCH' | 'MISMATCH' | 'NOT_COMPARABLE'
  document_value: string | null
  invoice_value: string
  message: string
}

export interface DocumentExplanation {
  summary: string
  generated_by: 'AI' | 'RULES'
  ai_note: string | null
  missing_fields: string[]
  needs_verification: string[]
  findings: DocumentFinding[]
}

export interface DocumentListParams {
  page: number
  page_size: number
  search?: string
  document_type?: DocumentType
  extraction_status?: ExtractionStatus
  verification_status?: VerificationStatus
}

export interface VerifyPayload {
  decision: 'VERIFIED' | 'REJECTED'
  fields?: FieldValues
  note?: string
}
