export const INVOICE_STATUSES = ['DRAFT', 'OPEN', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'CANCELLED'] as const
export type InvoiceStatus = (typeof INVOICE_STATUSES)[number]

export const SUPPORTED_CURRENCIES = ['USD', 'EUR', 'GBP', 'AED', 'INR'] as const
export type Currency = (typeof SUPPORTED_CURRENCIES)[number]

/** Money values are decimal strings (e.g. "12500.00"), never JS numbers. */
export interface InvoiceListItem {
  id: string
  invoice_number: string
  buyer_name: string
  buyer_country: string
  exporter_name: string
  invoice_date: string
  due_date: string
  currency: string
  total_amount: string
  amount_received: string
  outstanding_amount: string
  status: InvoiceStatus
}

export interface InvoicePayment {
  id: string
  payment_id: string
  transaction_reference: string
  sender_name: string
  transaction_date: string
  allocated_amount: string
  currency: string
  allocation_type: 'AUTO' | 'MANUAL'
  created_at: string
}

export interface InvoiceDetail extends InvoiceListItem {
  exporter_id: string
  buyer_id: string
  description: string | null
  payment_terms: string | null
  created_at: string
  updated_at: string
  payments: InvoicePayment[]
  has_payments: boolean
  is_editable: boolean
}

export interface Party {
  id: string
  name: string
  country: string
}

export type InvoiceSortField = 'invoice_date' | 'due_date' | 'total_amount' | 'invoice_number' | 'outstanding_amount'

export interface InvoiceListParams {
  page: number
  page_size: number
  search?: string
  status?: InvoiceStatus
  currency?: string
  date_from?: string
  date_to?: string
  sort_by: InvoiceSortField
  sort_dir: 'asc' | 'desc'
}

/** Request body for create (POST) and full update (PUT). */
export interface InvoicePayload {
  invoice_number: string
  exporter_id: string
  buyer_name: string
  buyer_country: string
  invoice_date: string
  due_date: string
  currency: string
  total_amount: string
  description: string | null
  payment_terms: string | null
}

export interface InvoiceCreatePayload extends InvoicePayload {
  status: 'DRAFT' | 'OPEN'
}
