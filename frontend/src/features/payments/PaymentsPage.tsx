import { Download, FileSearch, FileSpreadsheet, Search, UploadCloud, Wallet, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { PageHeader } from '@/components/common/PageHeader'
import { Pagination } from '@/components/common/Pagination'
import { SortableHead } from '@/components/common/SortableHead'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useUrlParams } from '@/hooks/useUrlParams'
import { getErrorMessage } from '@/lib/api'
import { downloadBlob } from '@/lib/download'
import { formatDate, formatDateTime, formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import { downloadImportErrorReport } from '@/services/payments'
import { SUPPORTED_CURRENCIES } from '@/types/invoice'
import {
  RECONCILIATION_STATUSES,
  type PaymentListParams,
  type PaymentSortField,
  type ReconciliationStatus,
} from '@/types/payment'

import { usePayments, useRecentImports } from './hooks'
import { ImportPaymentsSheet } from './ImportPaymentsSheet'
import { PaymentStatusBadge, RECONCILIATION_STATUS_LABELS } from './PaymentStatusBadge'

const PAGE_SIZE = 10
const SORT_FIELDS: PaymentSortField[] = ['transaction_date', 'created_at', 'amount', 'transaction_reference', 'sender_name']

function parseParams(sp: URLSearchParams): PaymentListParams {
  const status = sp.get('status')
  const sort = sp.get('sort') as PaymentSortField | null
  return {
    page: Math.max(1, Number(sp.get('page')) || 1),
    page_size: PAGE_SIZE,
    search: sp.get('q') || undefined,
    currency: sp.get('currency') || undefined,
    status: RECONCILIATION_STATUSES.includes(status as ReconciliationStatus) ? (status as ReconciliationStatus) : undefined,
    date_from: sp.get('from') || undefined,
    date_to: sp.get('to') || undefined,
    import_batch_id: sp.get('batch') || undefined,
    sort_by: sort && SORT_FIELDS.includes(sort) ? sort : 'transaction_date',
    sort_dir: sp.get('dir') === 'asc' ? 'asc' : 'desc',
  }
}

export default function PaymentsPage() {
  const { searchParams, update, clear } = useUrlParams()
  const params = parseParams(searchParams)

  const [importOpen, setImportOpen] = useState(false)
  const [searchInput, setSearchInput] = useState(params.search ?? '')
  const debouncedSearch = useDebouncedValue(searchInput)

  const { data, isPending, isError, error, refetch, isFetching } = usePayments(params)

  useEffect(() => {
    if ((params.search ?? '') !== debouncedSearch.trim()) update({ q: debouncedSearch.trim() || undefined })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch])

  const hasFilters = !!(
    params.search ||
    params.currency ||
    params.status ||
    params.date_from ||
    params.date_to ||
    params.import_batch_id
  )
  const clearFilters = () => {
    setSearchInput('')
    clear()
  }

  const sortProps = (field: PaymentSortField) => ({
    active: params.sort_by === field,
    direction: params.sort_dir,
    onSort: () => update({ sort: field, dir: params.sort_by === field && params.sort_dir === 'desc' ? 'asc' : 'desc' }),
  })

  return (
    <>
      <PageHeader
        title="Payments"
        description="Import bank transactions and track every payment received."
        actions={
          <Button onClick={() => setImportOpen(true)}>
            <UploadCloud className="size-4" /> Import CSV
          </Button>
        }
      />

      <RecentImports activeBatch={params.import_batch_id} onFilter={(id) => update({ batch: id })} />

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-end gap-3 border-b p-4">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search payments"
              placeholder="Search transaction, reference or sender"
              className="pl-8"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
          <NativeSelect
            aria-label="Filter by currency"
            className="w-32"
            value={params.currency ?? ''}
            onChange={(e) => update({ currency: e.target.value || undefined })}
          >
            <option value="">All currencies</option>
            {SUPPORTED_CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label="Filter by reconciliation status"
            className="w-44"
            value={params.status ?? ''}
            onChange={(e) => update({ status: e.target.value || undefined })}
          >
            <option value="">All statuses</option>
            {RECONCILIATION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {RECONCILIATION_STATUS_LABELS[s]}
              </option>
            ))}
          </NativeSelect>
          <div className="flex items-center gap-2">
            <Input
              type="date"
              aria-label="Transaction date from"
              className="w-36"
              value={params.date_from ?? ''}
              onChange={(e) => update({ from: e.target.value || undefined })}
            />
            <span className="text-sm text-muted-foreground">to</span>
            <Input
              type="date"
              aria-label="Transaction date to"
              className="w-36"
              value={params.date_to ?? ''}
              onChange={(e) => update({ to: e.target.value || undefined })}
            />
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="size-4" /> Clear
            </Button>
          )}
        </div>

        {isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} title="Could not load payments" />
        ) : isPending ? (
          <div className="space-y-3 p-4" role="status" aria-label="Loading payments">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : data.total === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={FileSearch}
              title="No payments match your filters"
              description="Try a different search or clear the filters."
              action={
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={Wallet}
              title="No payments yet"
              description="Import a bank transaction CSV to see payments here."
              action={
                <Button onClick={() => setImportOpen(true)}>
                  <UploadCloud className="size-4" /> Import CSV
                </Button>
              }
            />
          )
        ) : (
          <>
            <div className={cn('transition-opacity', isFetching && 'opacity-60')}>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <SortableHead {...sortProps('transaction_reference')}>Transaction</SortableHead>
                    <TableHead>Payment ref.</TableHead>
                    <SortableHead {...sortProps('sender_name')}>Sender</SortableHead>
                    <TableHead>Cur.</TableHead>
                    <SortableHead {...sortProps('amount')} align="right">
                      Amount
                    </SortableHead>
                    <SortableHead {...sortProps('transaction_date')}>Transaction date</SortableHead>
                    <SortableHead {...sortProps('created_at')}>Imported</SortableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="font-medium">{p.transaction_reference}</TableCell>
                      <TableCell className="text-muted-foreground">{p.payment_reference ?? '—'}</TableCell>
                      <TableCell>{p.sender_name}</TableCell>
                      <TableCell className="text-muted-foreground">{p.currency}</TableCell>
                      <TableCell className="text-right font-medium whitespace-nowrap tabular-nums">
                        {formatMoney(p.amount, p.currency)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{formatDate(p.transaction_date)}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(p.created_at)}</TableCell>
                      <TableCell>
                        <PaymentStatusBadge status={p.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <Pagination
              page={data.page}
              pages={data.pages}
              total={data.total}
              pageSize={data.page_size}
              onPageChange={(page) => update({ page: String(page) })}
            />
          </>
        )}
      </Card>

      <ImportPaymentsSheet open={importOpen} onOpenChange={setImportOpen} />
    </>
  )
}

/** Last few imports, so a file's rows and its error report can be revisited. */
function RecentImports({ activeBatch, onFilter }: { activeBatch?: string; onFilter: (batchId?: string) => void }) {
  const { data } = useRecentImports()
  if (!data || data.length === 0) return null

  const downloadErrors = async (batchId: string) => {
    try {
      downloadBlob(await downloadImportErrorReport(batchId), `import-errors-${batchId.slice(0, 8)}.csv`)
    } catch (error) {
      toast.error(getErrorMessage(error))
    }
  }

  return (
    <Card className="mb-6 py-0">
      <CardContent className="p-0">
        <p className="border-b px-4 py-3 text-sm font-medium text-navy">Recent imports</p>
        <ul className="divide-y">
          {data.map((batch) => {
            const skipped = batch.rejected_rows + batch.duplicate_rows
            const active = activeBatch === batch.id
            return (
              <li key={batch.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 text-sm">
                <div className="flex min-w-0 items-center gap-2">
                  <FileSpreadsheet className="size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate font-medium">{batch.file_name}</span>
                  <span className="text-muted-foreground">{formatDateTime(batch.created_at)}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-muted-foreground">
                    <span className="font-medium text-success">{batch.accepted_rows}</span> imported
                    {skipped > 0 && (
                      <>
                        {' · '}
                        <span className="font-medium text-warning">{skipped}</span> skipped
                      </>
                    )}
                  </span>
                  {skipped > 0 && (
                    <Button variant="ghost" size="sm" onClick={() => void downloadErrors(batch.id)}>
                      <Download className="size-4" /> Error report
                    </Button>
                  )}
                  <Button variant={active ? 'secondary' : 'outline'} size="sm" onClick={() => onFilter(active ? undefined : batch.id)}>
                    {active ? 'Showing this file' : 'View payments'}
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}
