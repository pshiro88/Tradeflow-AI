import { FileCheck2, FileSearch, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { PageHeader } from '@/components/common/PageHeader'
import { Pagination } from '@/components/common/Pagination'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { InvoiceStatusBadge } from '@/features/invoices/InvoiceStatusBadge'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useUrlParams } from '@/hooks/useUrlParams'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'

import { ChecklistSheet } from './ChecklistSheet'
import { useComplianceList } from './hooks'

const PAGE_SIZE = 10

export default function CompliancePage() {
  const { searchParams, update, clear } = useUrlParams()
  const params = {
    page: Math.max(1, Number(searchParams.get('page')) || 1),
    page_size: PAGE_SIZE,
    search: searchParams.get('q') || undefined,
    incomplete_only: searchParams.get('incomplete') === '1' ? true : undefined,
  }
  const [selected, setSelected] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState(params.search ?? '')
  const debounced = useDebouncedValue(searchInput)
  const { data, isPending, isError, error, refetch, isFetching } = useComplianceList(params)

  useEffect(() => {
    if ((params.search ?? '') !== debounced.trim()) update({ q: debounced.trim() || undefined })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  const hasFilters = !!(params.search || params.incomplete_only)
  const clearFilters = () => {
    setSearchInput('')
    clear()
  }

  return (
    <>
      <PageHeader
        title="Compliance"
        description="Is the paperwork for each invoice on file, verified, and consistent with the invoice?"
      />
      <p className="mb-4 text-sm text-muted-foreground">
        This is an operational checklist, not regulatory approval. Completing it does not file anything with any authority.
      </p>

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input aria-label="Search invoices" placeholder="Search invoice number or buyer" className="pl-8" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
          </div>
          <Button
            variant={params.incomplete_only ? 'secondary' : 'outline'}
            aria-pressed={!!params.incomplete_only}
            onClick={() => update({ incomplete: params.incomplete_only ? undefined : '1' })}
          >
            Incomplete only
          </Button>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="size-4" /> Clear
            </Button>
          )}
        </div>

        {isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} title="Could not load the checklists" />
        ) : isPending ? (
          <div className="space-y-3 p-4" role="status" aria-label="Loading checklists">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : data.total === 0 ? (
          hasFilters ? (
            <EmptyState icon={FileSearch} title="No invoices match your filters" action={<Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>} />
          ) : (
            <EmptyState icon={FileCheck2} title="No issued invoices yet" description="Documents are tracked for issued invoices." />
          )
        ) : (
          <>
            <div className={cn('transition-opacity', isFetching && 'opacity-60')}>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead>Invoice</TableHead>
                    <TableHead>Buyer</TableHead>
                    <TableHead>Due</TableHead>
                    <TableHead>Invoice status</TableHead>
                    <TableHead>Documents verified</TableHead>
                    <TableHead>Attention</TableHead>
                    <TableHead>Filing readiness</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((row) => {
                    const percent = row.required_total ? Math.round((row.verified / row.required_total) * 100) : 0
                    return (
                      <TableRow key={row.invoice_id} tabIndex={0} className="cursor-pointer" onClick={() => setSelected(row.invoice_id)} onKeyDown={(e) => e.key === 'Enter' && setSelected(row.invoice_id)}>
                        <TableCell className="font-medium">{row.invoice_number}</TableCell>
                        <TableCell>{row.buyer_name}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDate(row.due_date)}</TableCell>
                        <TableCell>
                          <InvoiceStatusBadge status={row.invoice_status} />
                        </TableCell>
                        <TableCell className="min-w-40">
                          <div className="flex items-center gap-2">
                            <div role="progressbar" aria-label={`${row.verified} of ${row.required_total} verified`} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                              <div className="h-full rounded-full bg-success" style={{ width: `${percent}%` }} />
                            </div>
                            <span className="text-sm tabular-nums">
                              {row.verified}/{row.required_total}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1.5">
                            {row.missing > 0 && <StatusBadge label={`${row.missing} missing`} tone="danger" />}
                            {row.flagged > 0 && <StatusBadge label={`${row.flagged} differ`} tone="warning" />}
                            {row.missing === 0 && row.flagged === 0 && <span className="text-sm text-muted-foreground">{row.complete ? 'Complete' : 'In review'}</span>}
                          </div>
                        </TableCell>
                        <TableCell>
                          <StatusBadge label={row.ready ? 'Ready' : 'Not ready'} tone={row.ready ? 'success' : 'neutral'} />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
            <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={(page) => update({ page: String(page) })} />
          </>
        )}
      </Card>

      <ChecklistSheet invoiceId={selected} onClose={() => setSelected(null)} />
    </>
  )
}
