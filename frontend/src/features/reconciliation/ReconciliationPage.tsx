import { AlertTriangle, FileSearch, Loader2, Play, Scale, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { PageHeader } from '@/components/common/PageHeader'
import { Pagination } from '@/components/common/Pagination'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { PaymentStatusBadge, RECONCILIATION_STATUS_LABELS } from '@/features/payments/PaymentStatusBadge'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useUrlParams } from '@/hooks/useUrlParams'
import { getErrorMessage } from '@/lib/api'
import { formatDate, formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import { RECONCILIATION_STATUSES, type ReconciliationStatus } from '@/types/payment'
import type { ReconciliationListParams } from '@/types/reconciliation'

import { useReconciliationResults, useReconciliationSummary, useRunReconciliation } from './hooks'
import { confidenceLabel, methodLabel } from './labels'
import { ReviewSheet } from './ReviewSheet'

const PAGE_SIZE = 10

// Result statuses shown as filter cards (PENDING means "not processed yet" and has no result row).
const CARDS: { status: ReconciliationStatus; tone: string }[] = [
  { status: 'MATCHED', tone: 'text-success' },
  { status: 'PARTIAL', tone: 'text-warning' },
  { status: 'UNMATCHED', tone: 'text-destructive' },
  { status: 'MISMATCH', tone: 'text-destructive' },
  { status: 'MANUAL_REVIEW', tone: 'text-primary' },
  { status: 'DUPLICATE', tone: 'text-warning' },
]

function parseParams(sp: URLSearchParams): ReconciliationListParams {
  const status = sp.get('status')
  return {
    page: Math.max(1, Number(sp.get('page')) || 1),
    page_size: PAGE_SIZE,
    status: RECONCILIATION_STATUSES.includes(status as ReconciliationStatus) ? (status as ReconciliationStatus) : undefined,
    needs_review: sp.get('review') === '1' ? true : undefined,
    search: sp.get('q') || undefined,
  }
}

export default function ReconciliationPage() {
  const { searchParams, update, clear } = useUrlParams()
  const params = parseParams(searchParams)

  const [searchInput, setSearchInput] = useState(params.search ?? '')
  const debouncedSearch = useDebouncedValue(searchInput)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const summary = useReconciliationSummary()
  const results = useReconciliationResults(params)
  const run = useRunReconciliation()

  useEffect(() => {
    if ((params.search ?? '') !== debouncedSearch.trim()) update({ q: debouncedSearch.trim() || undefined })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch])

  const counts = summary.data?.counts ?? {}
  const pending = counts.PENDING ?? 0
  const hasFilters = !!(params.status || params.needs_review || params.search)
  const clearFilters = () => {
    setSearchInput('')
    clear()
  }

  const runNow = () =>
    run.mutate(undefined, {
      onSuccess: (r) => {
        if (r.processed === 0) return toast.info('Nothing to reconcile: no pending payments.')
        const parts = Object.entries(r.counts).map(([status, n]) => `${n} ${RECONCILIATION_STATUS_LABELS[status as ReconciliationStatus].toLowerCase()}`)
        toast.success(`Reconciled ${r.processed} payments: ${parts.join(', ')}`)
      },
      onError: (e) => toast.error(getErrorMessage(e)),
    })

  return (
    <>
      <PageHeader
        title="Reconciliation"
        description="Match incoming payments to invoices with deterministic rules, and review the exceptions."
        actions={
          <Button onClick={runNow} disabled={run.isPending}>
            {run.isPending ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
            Run reconciliation
          </Button>
        }
      />

      {pending > 0 && (
        <p className="mb-4 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
          <AlertTriangle className="size-4 shrink-0" />
          {pending} imported payment{pending === 1 ? ' has' : 's have'} not been reconciled yet. Run reconciliation to
          process {pending === 1 ? 'it' : 'them'}.
        </p>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" aria-label="Reconciliation summary">
        {CARDS.map(({ status, tone }) => {
          const active = params.status === status
          return (
            <button
              key={status}
              type="button"
              aria-pressed={active}
              onClick={() => update({ status: active ? undefined : status, review: undefined })}
              className={cn(
                'rounded-xl border bg-card p-4 text-left transition-colors hover:border-primary/40 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none',
                active && 'border-primary ring-2 ring-primary/20',
              )}
            >
              <p className="text-xs text-muted-foreground">{RECONCILIATION_STATUS_LABELS[status]}</p>
              {summary.isPending ? (
                <Skeleton className="mt-1 h-8 w-10" />
              ) : (
                <p className={cn('text-2xl font-semibold tabular-nums', tone)}>{counts[status] ?? 0}</p>
              )}
            </button>
          )
        })}
      </div>

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search results"
              placeholder="Search transaction, reference, sender or invoice"
              className="pl-8"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
          <Button
            variant={params.needs_review ? 'secondary' : 'outline'}
            aria-pressed={!!params.needs_review}
            onClick={() => update({ review: params.needs_review ? undefined : '1', status: undefined })}
          >
            Needs review
            <span className="rounded-full bg-primary/10 px-2 text-xs font-medium text-primary">
              {summary.data?.needs_review ?? 0}
            </span>
          </Button>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="size-4" /> Clear
            </Button>
          )}
        </div>

        {results.isError ? (
          <ErrorState error={results.error} onRetry={() => void results.refetch()} title="Could not load results" />
        ) : results.isPending ? (
          <div className="space-y-3 p-4" role="status" aria-label="Loading results">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : results.data.total === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={FileSearch}
              title="No results match your filters"
              action={
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={Scale}
              title="Nothing reconciled yet"
              description="Import bank payments, then run reconciliation to match them to invoices."
            />
          )
        ) : (
          <>
            <div className={cn('transition-opacity', results.isFetching && 'opacity-60')}>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead>Transaction</TableHead>
                    <TableHead>Invoice</TableHead>
                    <TableHead className="text-right">Invoice amount</TableHead>
                    <TableHead className="text-right">Payment</TableHead>
                    <TableHead className="text-right">Previously received</TableHead>
                    <TableHead className="text-right">Outstanding after</TableHead>
                    <TableHead>Method</TableHead>
                    <TableHead className="text-right">Conf.</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Explanation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.data.items.map((r) => (
                    <TableRow
                      key={r.id}
                      tabIndex={0}
                      className="cursor-pointer"
                      onClick={() => setSelectedId(r.id)}
                      onKeyDown={(e) => e.key === 'Enter' && setSelectedId(r.id)}
                    >
                      <TableCell>
                        <p className="font-medium">{r.transaction_reference}</p>
                        <p className="text-xs text-muted-foreground">
                          {r.sender_name} · {formatDate(r.transaction_date)}
                        </p>
                      </TableCell>
                      <TableCell className="font-medium">{r.invoice_number ?? <span className="text-muted-foreground">—</span>}</TableCell>
                      <TableCell className="text-right whitespace-nowrap tabular-nums">
                        {r.invoice_amount ? formatMoney(r.invoice_amount, r.invoice_currency ?? r.currency) : '—'}
                      </TableCell>
                      <TableCell className="text-right font-medium whitespace-nowrap tabular-nums">
                        {formatMoney(r.payment_amount, r.currency)}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap text-muted-foreground tabular-nums">
                        {r.previously_received ? formatMoney(r.previously_received, r.invoice_currency ?? r.currency) : '—'}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap tabular-nums">
                        {r.outstanding_after ? formatMoney(r.outstanding_after, r.invoice_currency ?? r.currency) : '—'}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{methodLabel(r.match_method)}</TableCell>
                      <TableCell className="text-right text-muted-foreground tabular-nums">{confidenceLabel(r.confidence)}</TableCell>
                      <TableCell>
                        <PaymentStatusBadge status={r.status} />
                      </TableCell>
                      <TableCell className="max-w-xs min-w-60 text-sm whitespace-normal text-muted-foreground">
                        <p className="line-clamp-2" title={r.explanation ?? undefined}>
                          {r.explanation}
                        </p>
                        {r.needs_review && <p className="mt-1 text-xs font-medium text-primary">Click to review</p>}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <Pagination
              page={results.data.page}
              pages={results.data.pages}
              total={results.data.total}
              pageSize={results.data.page_size}
              onPageChange={(page) => update({ page: String(page) })}
            />
          </>
        )}
      </Card>

      <ReviewSheet resultId={selectedId} onClose={() => setSelectedId(null)} />
    </>
  )
}
