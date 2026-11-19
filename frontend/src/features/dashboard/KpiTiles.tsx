import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { CurrencyAmount, DashboardFilters, DashboardSummary } from '@/types/dashboard'

import { useDashboardSummary } from './hooks'

/** One line per currency: totals in different currencies are never added together. */
function MoneyLines({ amounts, size = 'lg' }: { amounts: CurrencyAmount[]; size?: 'lg' | 'sm' }) {
  if (amounts.length === 0) return <p className="text-2xl font-semibold text-muted-foreground">—</p>
  return (
    <ul className="space-y-0.5">
      {amounts.map((a) => (
        <li key={a.currency} className={cn('font-semibold text-navy', size === 'lg' ? 'text-lg' : 'text-sm font-medium text-muted-foreground')}>
          {formatMoney(a.amount, a.currency)}
        </li>
      ))}
    </ul>
  )
}

interface TileProps {
  label: string
  children: ReactNode
  hint?: ReactNode
  /** Makes the whole tile a link to the underlying records. */
  to?: string
  tone?: 'danger' | 'warning'
}

function Tile({ label, children, hint, to, tone }: TileProps) {
  const body = (
    <Card
      data-tile={to ? undefined : label}
      className={cn(
        'h-full gap-2 p-4 transition-colors',
        to && 'hover:border-primary/40',
        tone === 'danger' && 'border-destructive/30',
      )}
    >
      <p className="text-sm text-muted-foreground">{label}</p>
      <div>{children}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </Card>
  )
  return to ? (
    <Link to={to} data-tile={label} className="rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">
      {body}
    </Link>
  ) : (
    body
  )
}

function Count({ value, tone }: { value: number; tone?: 'danger' | 'warning' | 'success' }) {
  // Proportional figures (not tabular) for large standalone numbers.
  return (
    <p
      className={cn(
        'text-3xl font-semibold tracking-tight',
        tone === 'danger' && value > 0 && 'text-destructive',
        tone === 'warning' && value > 0 && 'text-warning',
        tone === 'success' && 'text-success',
        !tone && 'text-navy',
      )}
    >
      {value}
    </p>
  )
}

export function KpiTiles({ filters }: { filters: DashboardFilters }) {
  const { data, isPending, isFetching } = useDashboardSummary(filters)

  if (isPending || !data) {
    return (
      <div className="space-y-4" role="status" aria-label="Loading key figures">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      </div>
    )
  }
  const s: DashboardSummary = data
  return (
    <section aria-label="Key figures" className={cn('space-y-4 transition-opacity', isFetching && 'opacity-60')}>
      {/* Money: one line per currency, never summed across currencies. */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Tile label="Total invoice value" hint="Per currency, not converted">
          <MoneyLines amounts={s.total_invoice_value} />
        </Tile>
        <Tile
          label="Payments received"
          hint={
            s.unallocated_received.length > 0 ? (
              <>
                <p className="mb-0.5">Not yet applied to invoices:</p>
                <MoneyLines amounts={s.unallocated_received} size="sm" />
              </>
            ) : (
              'Bank receipts, duplicates excluded'
            )
          }
          to="/payments"
        >
          <MoneyLines amounts={s.payments_received} />
        </Tile>
        <Tile label="Pending payment amount" hint="Outstanding on issued invoices">
          <MoneyLines amounts={s.pending_amount} />
        </Tile>
      </div>
      {/* Counts */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <Tile label="Export invoices" hint="Issued, excluding drafts and cancelled" to="/invoices">
          <Count value={s.total_invoices} />
        </Tile>
        <Tile label="Fully reconciled invoices" hint="Paid in full" to="/invoices?status=PAID">
          <Count value={s.fully_reconciled_invoices} tone="success" />
        </Tile>
        <Tile label="Partially paid invoices" hint="Some money received, balance remains">
          <Count value={s.partially_paid_invoices} tone="warning" />
        </Tile>
        <Tile label="Unmatched transactions" hint="No reliable invoice found" to="/reconciliation?status=UNMATCHED">
          <Count value={s.unmatched_transactions} tone="danger" />
        </Tile>
        <Tile label="Overdue invoices" hint="Past due with a balance" to="/invoices?status=OVERDUE" tone={s.overdue_invoices > 0 ? 'danger' : undefined}>
          <Count value={s.overdue_invoices} tone="danger" />
        </Tile>
      </div>
    </section>
  )
}
