import { StatusBadge, type StatusTone } from '@/components/common/StatusBadge'
import type { ReconciliationStatus } from '@/types/payment'

const STATUS_META: Record<ReconciliationStatus, { label: string; tone: StatusTone }> = {
  PENDING: { label: 'Pending', tone: 'neutral' },
  MATCHED: { label: 'Matched', tone: 'success' },
  PARTIAL: { label: 'Partial', tone: 'warning' },
  UNMATCHED: { label: 'Unmatched', tone: 'danger' },
  MISMATCH: { label: 'Mismatch', tone: 'danger' },
  DUPLICATE: { label: 'Duplicate', tone: 'warning' },
  MANUAL_REVIEW: { label: 'Manual review', tone: 'info' },
}

export const RECONCILIATION_STATUS_LABELS: Record<ReconciliationStatus, string> = Object.fromEntries(
  Object.entries(STATUS_META).map(([status, meta]) => [status, meta.label]),
) as Record<ReconciliationStatus, string>

export function PaymentStatusBadge({ status }: { status: ReconciliationStatus }) {
  const meta = STATUS_META[status]
  return <StatusBadge label={meta.label} tone={meta.tone} />
}
