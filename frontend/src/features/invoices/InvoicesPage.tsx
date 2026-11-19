import { FileSearch, Plus, Receipt, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { PageHeader } from '@/components/common/PageHeader'
import { Pagination } from '@/components/common/Pagination'
import { SortableHead } from '@/components/common/SortableHead'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useUrlParams } from '@/hooks/useUrlParams'
import { formatDate, formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  INVOICE_STATUSES,
  SUPPORTED_CURRENCIES,
  type InvoiceListParams,
  type InvoiceSortField,
  type InvoiceStatus,
} from '@/types/invoice'

import { useInvoices } from './hooks'
import { INVOICE_STATUS_LABELS, InvoiceStatusBadge } from './InvoiceStatusBadge'
import { InvoiceFormSheet } from './InvoiceFormSheet'

const PAGE_SIZE = 10
const SORT_FIELDS: InvoiceSortField[] = ['invoice_date', 'due_date', 'total_amount', 'invoice_number', 'outstanding_amount']

function parseParams(sp: URLSearchParams): InvoiceListParams {
  const status = sp.get('status')
  const sort = sp.get('sort') as InvoiceSortField | null
  return {
    page: Math.max(1, Number(sp.get('page')) || 1),
    page_size: PAGE_SIZE,
    search: sp.get('q') || undefined,
    status: INVOICE_STATUSES.includes(status as InvoiceStatus) ? (status as InvoiceStatus) : undefined,
    currency: sp.get('currency') || undefined,
    date_from: sp.get('from') || undefined,
    date_to: sp.get('to') || undefined,
    sort_by: sort && SORT_FIELDS.includes(sort) ? sort : 'invoice_date',
    sort_dir: sp.get('dir') === 'asc' ? 'asc' : 'desc',
  }
}

export default function InvoicesPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { searchParams, update, clear } = useUrlParams()
  const params = parseParams(searchParams)
  const canCreate = user?.role === 'ADMIN' || user?.role === 'FINANCE'

  const [formOpen, setFormOpen] = useState(false)
  const [searchInput, setSearchInput] = useState(params.search ?? '')
  const debouncedSearch = useDebouncedValue(searchInput)

  const { data, isPending, isError, error, refetch, isFetching } = useInvoices(params)

  // Push the debounced search text into the URL.
  useEffect(() => {
    if ((params.search ?? '') !== debouncedSearch.trim()) update({ q: debouncedSearch.trim() || undefined })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch])

  const hasFilters = !!(params.search || params.status || params.currency || params.date_from || params.date_to)
  const clearFilters = () => {
    setSearchInput('')
    clear()
  }

  const sortProps = (field: InvoiceSortField) => ({
    active: params.sort_by === field,
    direction: params.sort_dir,
    onSort: () => update({ sort: field, dir: params.sort_by === field && params.sort_dir === 'desc' ? 'asc' : 'desc' }),
  })

  return (
    <>
      <PageHeader
        title="Invoices"
        description="Create and manage export invoices and track what has been received."
        actions={
          canCreate && (
            <Button onClick={() => setFormOpen(true)}>
              <Plus className="size-4" /> New invoice
            </Button>
          )
        }
      />

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-end gap-3 border-b p-4">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search invoices"
              placeholder="Search invoice number or buyer"
              className="pl-8"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
          <NativeSelect
            aria-label="Filter by status"
            className="w-40"
            value={params.status ?? ''}
            onChange={(e) => update({ status: e.target.value || undefined })}
          >
            <option value="">All statuses</option>
            {INVOICE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {INVOICE_STATUS_LABELS[s]}
              </option>
            ))}
          </NativeSelect>
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
          <div className="flex items-center gap-2">
            <Input
              type="date"
              aria-label="Invoice date from"
              className="w-36"
              value={params.date_from ?? ''}
              onChange={(e) => update({ from: e.target.value || undefined })}
            />
            <span className="text-sm text-muted-foreground">to</span>
            <Input
              type="date"
              aria-label="Invoice date to"
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
          <ErrorState error={error} onRetry={() => void refetch()} title="Could not load invoices" />
        ) : isPending ? (
          <TableSkeleton />
        ) : data.total === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={FileSearch}
              title="No invoices match your filters"
              description="Try a different search term or clear the filters."
              action={
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={Receipt}
              title="No invoices yet"
              description="Create your first export invoice to start tracking payments."
              action={
                canCreate && (
                  <Button onClick={() => setFormOpen(true)}>
                    <Plus className="size-4" /> New invoice
                  </Button>
                )
              }
            />
          )
        ) : (
          <>
            <div className={cn('transition-opacity', isFetching && 'opacity-60')}>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <SortableHead {...sortProps('invoice_number')}>
                      Invoice
                    </SortableHead>
                    <TableHead>Buyer</TableHead>
                    <TableHead>Country</TableHead>
                    <SortableHead {...sortProps('invoice_date')}>
                      Invoice date
                    </SortableHead>
                    <SortableHead {...sortProps('due_date')}>
                      Due date
                    </SortableHead>
                    <TableHead>Cur.</TableHead>
                    <SortableHead {...sortProps('total_amount')} align="right">
                      Amount
                    </SortableHead>
                    <TableHead className="text-right">Received</TableHead>
                    <SortableHead {...sortProps('outstanding_amount')} align="right">
                      Outstanding
                    </SortableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((inv) => (
                    <TableRow
                      key={inv.id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/invoices/${inv.id}`)}
                    >
                      <TableCell className="font-medium">
                        <Link
                          to={`/invoices/${inv.id}`}
                          className="text-primary hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {inv.invoice_number}
                        </Link>
                      </TableCell>
                      <TableCell>{inv.buyer_name}</TableCell>
                      <TableCell className="text-muted-foreground">{inv.buyer_country}</TableCell>
                      <TableCell className="whitespace-nowrap">{formatDate(inv.invoice_date)}</TableCell>
                      <TableCell
                        className={cn('whitespace-nowrap', inv.status === 'OVERDUE' && 'font-medium text-destructive')}
                      >
                        {formatDate(inv.due_date)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{inv.currency}</TableCell>
                      <TableCell className="text-right whitespace-nowrap tabular-nums">
                        {formatMoney(inv.total_amount, inv.currency)}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap text-muted-foreground tabular-nums">
                        {formatMoney(inv.amount_received, inv.currency)}
                      </TableCell>
                      <TableCell className="text-right font-medium whitespace-nowrap tabular-nums">
                        {formatMoney(inv.outstanding_amount, inv.currency)}
                      </TableCell>
                      <TableCell>
                        <InvoiceStatusBadge status={inv.status} />
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

      <InvoiceFormSheet open={formOpen} onOpenChange={setFormOpen} onSaved={(inv) => navigate(`/invoices/${inv.id}`)} />
    </>
  )
}

function TableSkeleton() {
  return (
    <div className="space-y-3 p-4" aria-label="Loading invoices" role="status">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  )
}
