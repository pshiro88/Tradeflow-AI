import { ChartCard } from '@/components/charts/ChartCard'
import { RankedBars } from '@/components/charts/RankedBars'
import { ErrorState } from '@/components/common/ErrorState'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { RECONCILIATION_STATUS_LABELS } from '@/features/payments/PaymentStatusBadge'
import { formatMoney } from '@/lib/format'
import type { DashboardFilters } from '@/types/dashboard'

import { useCurrencyDistribution, usePaymentDistribution } from './hooks'

function ChartSkeleton({ title }: { title: string }) {
  return (
    <ChartCard
      title={title}
      chart={<Skeleton className="h-48 w-full" role="status" aria-label={`Loading ${title}`} />}
      table={null}
    />
  )
}

export function StatusDistributionCard({ filters }: { filters: DashboardFilters }) {
  const { data, isPending, isError, error, refetch, isFetching } = usePaymentDistribution(filters)
  const title = 'Payments by reconciliation status'
  if (isError) return <ChartCard title={title} chart={<ErrorState error={error} onRetry={() => void refetch()} />} table={null} />
  if (isPending) return <ChartSkeleton title={title} />

  // Largest first, zero-count statuses left out of the chart (they are in the table view).
  const ranked = data.items
    .filter((i) => i.count > 0)
    .sort((a, b) => b.count - a.count)
    .map((i) => ({
      label: RECONCILIATION_STATUS_LABELS[i.status],
      value: i.count,
      details: [{ label: 'Share', value: `${Math.round((i.count / data.total) * 100)}%` }],
    }))

  return (
    <ChartCard
      title={title}
      description={`${data.total} payment${data.total === 1 ? '' : 's'} in this view`}
      busy={isFetching}
      chart={
        ranked.length > 0 ? (
          <RankedBars
            data={ranked}
            measure="Payments"
            labelWidth={128}
            ariaLabel={`Ranked bars of payment counts by status: ${ranked.map((r) => `${r.label} ${r.value}`).join(', ')}.`}
          />
        ) : (
          <p className="py-12 text-center text-sm text-muted-foreground">No payments in this view.</p>
        )
      }
      table={
        <Table>
          <caption className="sr-only">Payments by reconciliation status</caption>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Payments</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((i) => (
              <TableRow key={i.status}>
                <TableCell>{RECONCILIATION_STATUS_LABELS[i.status]}</TableCell>
                <TableCell className="text-right tabular-nums">{i.count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    />
  )
}

export function CurrencyDistributionCard({ filters }: { filters: DashboardFilters }) {
  const { data, isPending, isError, error, refetch, isFetching } = useCurrencyDistribution(filters)
  const title = 'Invoices by currency'
  if (isError) return <ChartCard title={title} chart={<ErrorState error={error} onRetry={() => void refetch()} />} table={null} />
  if (isPending) return <ChartSkeleton title={title} />

  const ranked = [...data.items]
    .sort((a, b) => b.invoices - a.invoices || a.currency.localeCompare(b.currency))
    .map((i) => ({
      label: i.currency,
      value: i.invoices,
      details: [
        { label: 'Invoice value', value: formatMoney(i.invoice_value, i.currency) },
        { label: 'Payments', value: i.payments },
        { label: 'Received', value: formatMoney(i.received, i.currency) },
      ],
    }))

  return (
    <ChartCard
      title={title}
      description="Counted by number of invoices. Values are in each currency, never converted."
      busy={isFetching}
      chart={
        ranked.length > 0 ? (
          <RankedBars
            data={ranked}
            measure="Invoices"
            labelWidth={52}
            ariaLabel={`Ranked bars of invoice counts by currency: ${ranked.map((r) => `${r.label} ${r.value}`).join(', ')}.`}
          />
        ) : (
          <p className="py-12 text-center text-sm text-muted-foreground">No invoices in this view.</p>
        )
      }
      table={
        <Table>
          <caption className="sr-only">Invoices and payments by currency</caption>
          <TableHeader>
            <TableRow>
              <TableHead>Currency</TableHead>
              <TableHead className="text-right">Invoices</TableHead>
              <TableHead className="text-right">Invoice value</TableHead>
              <TableHead className="text-right">Payments</TableHead>
              <TableHead className="text-right">Received</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((i) => (
              <TableRow key={i.currency}>
                <TableCell className="font-medium">{i.currency}</TableCell>
                <TableCell className="text-right tabular-nums">{i.invoices}</TableCell>
                <TableCell className="text-right whitespace-nowrap tabular-nums">{formatMoney(i.invoice_value, i.currency)}</TableCell>
                <TableCell className="text-right tabular-nums">{i.payments}</TableCell>
                <TableCell className="text-right whitespace-nowrap tabular-nums">{formatMoney(i.received, i.currency)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    />
  )
}
