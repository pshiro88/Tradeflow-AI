export const RECONCILIATION_STATUSES = [
  'PENDING',
  'MATCHED',
  'PARTIAL',
  'UNMATCHED',
  'MISMATCH',
  'DUPLICATE',
  'MANUAL_REVIEW',
] as const
export type ReconciliationStatus = (typeof RECONCILIATION_STATUSES)[number]

/** Money values are decimal strings (e.g. "6000.00"), never JS numbers. */
export interface Payment {
  id: string
  transaction_reference: string
  payment_reference: string | null
  sender_name: string
  currency: string
  amount: string
  allocated_amount: string
  transaction_date: string
  created_at: string
  status: ReconciliationStatus
  import_batch_id: string | null
}

export type PaymentSortField = 'transaction_date' | 'created_at' | 'amount' | 'transaction_reference' | 'sender_name'

export interface PaymentListParams {
  page: number
  page_size: number
  search?: string
  currency?: string
  status?: ReconciliationStatus
  date_from?: string
  date_to?: string
  import_batch_id?: string
  sort_by: PaymentSortField
  sort_dir: 'asc' | 'desc'
}

export type ImportErrorCategory = 'VALIDATION' | 'DUPLICATE_IN_FILE' | 'DUPLICATE_EXISTING'

export interface ImportRowError {
  row: number
  transaction_reference: string | null
  category: ImportErrorCategory
  issues: { field: string; message: string }[]
  values: Record<string, string>
}

export interface ImportBatch {
  id: string
  file_name: string
  total_rows: number
  accepted_rows: number
  rejected_rows: number
  duplicate_rows: number
  created_at: string
}

export interface ImportBatchDetail extends ImportBatch {
  errors: ImportRowError[]
}
