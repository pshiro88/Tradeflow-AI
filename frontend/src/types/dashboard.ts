import type { ReconciliationStatus } from '@/types/payment'
import type { InvoiceStatus } from '@/types/invoice'

/** Money is always reported per currency; different currencies are never added together. */
export interface CurrencyAmount {
  currency: string
  amount: string
}

export interface DashboardSummary {
  total_invoices: number
  total_invoice_value: CurrencyAmount[]
  payments_received: CurrencyAmount[]
  unallocated_received: CurrencyAmount[]
  pending_amount: CurrencyAmount[]
  fully_reconciled_invoices: number
  partially_paid_invoices: number
  unmatched_transactions: number
  overdue_invoices: number
}

export interface TrendPoint {
  month: string // YYYY-MM
  invoiced: string
  received: string
}

export interface PaymentTrends {
  currency: string
  available_currencies: string[]
  points: TrendPoint[]
}

export interface StatusCount {
  status: ReconciliationStatus
  count: number
}

export interface PaymentDistribution {
  total: number
  items: StatusCount[]
}

export interface CurrencyShare {
  currency: string
  invoices: number
  payments: number
  invoice_value: string
  received: string
}

export interface CurrencyDistribution {
  items: CurrencyShare[]
}

export interface RecentTransaction {
  id: string
  transaction_reference: string
  sender_name: string
  buyer_name: string | null
  invoice_number: string | null
  currency: string
  amount: string
  transaction_date: string
  status: ReconciliationStatus
}

export interface OutstandingInvoice {
  id: string
  invoice_number: string
  buyer_name: string
  currency: string
  due_date: string
  outstanding_amount: string
  status: InvoiceStatus
  days_overdue: number // negative = days until due
}

/** Filters shared by every dashboard widget (BRD FR-005). */
export interface DashboardFilters {
  date_from?: string
  date_to?: string
  currency?: string
  status?: ReconciliationStatus
  buyer_id?: string
}
