import { X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { useBuyers } from '@/features/invoices/hooks'
import { RECONCILIATION_STATUS_LABELS } from '@/features/payments/PaymentStatusBadge'
import { useUrlParams } from '@/hooks/useUrlParams'
import type { DashboardFilters } from '@/types/dashboard'
import { SUPPORTED_CURRENCIES } from '@/types/invoice'
import { RECONCILIATION_STATUSES, type ReconciliationStatus } from '@/types/payment'

export function parseDashboardFilters(sp: URLSearchParams): DashboardFilters {
  const status = sp.get('status')
  return {
    date_from: sp.get('from') || undefined,
    date_to: sp.get('to') || undefined,
    currency: sp.get('currency') || undefined,
    status: RECONCILIATION_STATUSES.includes(status as ReconciliationStatus) ? (status as ReconciliationStatus) : undefined,
    buyer_id: sp.get('buyer') || undefined,
  }
}

/** The single filter row: every widget below re-renders against the same slice. */
export function DashboardFilterBar({ filters }: { filters: DashboardFilters }) {
  const { update, clear } = useUrlParams()
  const buyers = useBuyers()
  const active = Object.values(filters).some(Boolean)
  const rangeInvalid = !!(filters.date_from && filters.date_to && filters.date_from > filters.date_to)

  return (
    <div className="mb-6 space-y-2">
      <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Dashboard filters">
        <div className="space-y-1">
          <Label htmlFor="f-from" className="text-xs text-muted-foreground">
            From
          </Label>
          <Input id="f-from" type="date" className="w-38" value={filters.date_from ?? ''} onChange={(e) => update({ from: e.target.value || undefined })} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="f-to" className="text-xs text-muted-foreground">
            To
          </Label>
          <Input id="f-to" type="date" className="w-38" value={filters.date_to ?? ''} aria-invalid={rangeInvalid} onChange={(e) => update({ to: e.target.value || undefined })} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="f-currency" className="text-xs text-muted-foreground">
            Currency
          </Label>
          <NativeSelect id="f-currency" className="w-32" value={filters.currency ?? ''} onChange={(e) => update({ currency: e.target.value || undefined })}>
            <option value="">All</option>
            {SUPPORTED_CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="f-status" className="text-xs text-muted-foreground">
            Payment status
          </Label>
          <NativeSelect id="f-status" className="w-44" value={filters.status ?? ''} onChange={(e) => update({ status: e.target.value || undefined })}>
            <option value="">All</option>
            {RECONCILIATION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {RECONCILIATION_STATUS_LABELS[s]}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="f-buyer" className="text-xs text-muted-foreground">
            Buyer
          </Label>
          <NativeSelect id="f-buyer" className="w-56" value={filters.buyer_id ?? ''} onChange={(e) => update({ buyer: e.target.value || undefined })}>
            <option value="">All buyers</option>
            {buyers.data?.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        {active && (
          <Button variant="ghost" size="sm" onClick={clear}>
            <X className="size-4" /> Clear
          </Button>
        )}
      </div>
      {rangeInvalid ? (
        <p role="alert" className="text-sm text-destructive">
          The start date is after the end date, so the figures below cannot be filtered.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Dates filter invoices by invoice date and payments by transaction date. Payment status narrows payment figures
          only; buyer also narrows payments to those applied to that buyer's invoices.
        </p>
      )}
    </div>
  )
}
