import { CheckCircle2, Wallet } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { InvoiceStatusBadge } from '@/features/invoices/InvoiceStatusBadge'
import { PaymentStatusBadge } from '@/features/payments/PaymentStatusBadge'
import { formatDate, formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DashboardFilters } from '@/types/dashboard'

import { useOutstandingInvoices, useRecentTransactions } from './hooks'

export function RecentTransactionsCard({ filters }: { filters: DashboardFilters }) {
  const { data, isPending, isError, error, refetch, isFetching } = useRecentTransactions(filters)

  return (
    <Card className="gap-0 py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="font-medium text-navy">Recent transactions</h2>
        <Link to="/payments" className="text-sm text-primary hover:underline">
          All payments
        </Link>
      </div>
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-2 p-4" role="status" aria-label="Loading recent transactions">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <EmptyState icon={Wallet} title="No transactions in this view" description="Import a bank CSV or adjust the filters." />
      ) : (
        <div className={cn('transition-opacity', isFetching && 'opacity-60')}>
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 hover:bg-muted/40">
                <TableHead>Transaction</TableHead>
                <TableHead>Buyer / sender</TableHead>
                <TableHead>Cur.</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-medium">{t.transaction_reference}</TableCell>
                  <TableCell>
                    {t.buyer_name ?? (
                      <span className="text-muted-foreground" title="Not applied to a buyer's invoice">
                        {t.sender_name}
                      </span>
                    )}
                    {t.invoice_number && <span className="ml-1.5 text-xs text-muted-foreground">· {t.invoice_number}</span>}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{t.currency}</TableCell>
                  <TableCell className="text-right font-medium whitespace-nowrap tabular-nums">{formatMoney(t.amount, t.currency)}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatDate(t.transaction_date)}</TableCell>
                  <TableCell>
                    <PaymentStatusBadge status={t.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  )
}

function dueText(days: number): string {
  if (days > 0) return `${days} day${days === 1 ? '' : 's'} overdue`
  if (days === 0) return 'Due today'
  return `Due in ${-days} day${days === -1 ? '' : 's'}`
}

export function OutstandingInvoicesCard({ filters }: { filters: DashboardFilters }) {
  const { data, isPending, isError, error, refetch, isFetching } = useOutstandingInvoices(filters)

  return (
    <Card className="gap-0 py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="font-medium text-navy">Outstanding invoices</h2>
        <Link to="/invoices" className="text-sm text-primary hover:underline">
          All invoices
        </Link>
      </div>
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-2 p-4" role="status" aria-label="Loading outstanding invoices">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <EmptyState icon={CheckCircle2} title="Nothing outstanding" description="Every issued invoice in this view is settled." />
      ) : (
        <ul className={cn('divide-y transition-opacity', isFetching && 'opacity-60')}>
          {data.map((inv) => (
            <li key={inv.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <div className="min-w-0">
                <Link to={`/invoices/${inv.id}`} className="font-medium text-primary hover:underline">
                  {inv.invoice_number}
                </Link>
                <p className="truncate text-muted-foreground">{inv.buyer_name}</p>
                <p className={cn('text-xs', inv.days_overdue > 0 ? 'font-medium text-destructive' : 'text-muted-foreground')}>
                  {dueText(inv.days_overdue)}
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className="font-medium whitespace-nowrap tabular-nums">{formatMoney(inv.outstanding_amount, inv.currency)}</span>
                <InvoiceStatusBadge status={inv.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
