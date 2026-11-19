import { StatusBadge, type StatusTone } from '@/components/common/StatusBadge'
import type { InvoiceStatus } from '@/types/invoice'

const STATUS_META: Record<InvoiceStatus, { label: string; tone: StatusTone }> = {
  DRAFT: { label: 'Draft', tone: 'neutral' },
  OPEN: { label: 'Open', tone: 'info' },
  PARTIALLY_PAID: { label: 'Partially paid', tone: 'warning' },
  PAID: { label: 'Paid', tone: 'success' },
  OVERDUE: { label: 'Overdue', tone: 'danger' },
  CANCELLED: { label: 'Cancelled', tone: 'neutral' },
}

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = Object.fromEntries(
  Object.entries(STATUS_META).map(([status, meta]) => [status, meta.label]),
) as Record<InvoiceStatus, string>

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  const meta = STATUS_META[status]
  return <StatusBadge label={meta.label} tone={meta.tone} />
}
