import { differenceInCalendarDays, parseISO } from 'date-fns'
import { ArrowLeft, Ban, CheckCircle2, Loader2, Pencil, Wallet } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { PageHeader } from '@/components/common/PageHeader'
import { StatusBadge } from '@/components/common/StatusBadge'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/useAuth'
import { getErrorMessage } from '@/lib/api'
import { formatDate, formatDateTime, formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { InvoiceDetail } from '@/types/invoice'

import { LifecycleTimeline } from '@/features/compliance/LifecycleTimeline'

import { useChangeInvoiceStatus, useInvoice } from './hooks'
import { InvoiceFormSheet } from './InvoiceFormSheet'
import { InvoiceStatusBadge } from './InvoiceStatusBadge'

export default function InvoiceDetailPage() {
  const { invoiceId = '' } = useParams()
  const { user } = useAuth()
  const { data: invoice, isPending, isError, error, refetch } = useInvoice(invoiceId)
  const canManage = user?.role === 'ADMIN' || user?.role === 'FINANCE'

  const [editOpen, setEditOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const changeStatus = useChangeInvoiceStatus(invoiceId)

  if (isPending) return <DetailSkeleton />
  if (isError) {
    return (
      <>
        <BackLink />
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} title="Could not load this invoice" />
        </Card>
      </>
    )
  }

  const run = async (status: 'OPEN' | 'CANCELLED', successMessage: string) => {
    try {
      await changeStatus.mutateAsync(status)
      toast.success(successMessage)
      setCancelOpen(false)
    } catch (e) {
      toast.error(getErrorMessage(e))
      setCancelOpen(false)
    }
  }

  const received = Number(invoice.amount_received)
  const total = Number(invoice.total_amount)
  // Display-only ratio for the progress bar; no money arithmetic happens in the browser.
  const percentReceived = total > 0 ? Math.min(100, Math.round((received / total) * 100)) : 0

  return (
    <>
      <BackLink />
      <PageHeader
        title={invoice.invoice_number}
        description={`${invoice.buyer_name} · ${invoice.exporter_name}`}
        actions={
          <>
            <InvoiceStatusBadge status={invoice.status} />
            {canManage && invoice.status === 'DRAFT' && (
              <Button onClick={() => void run('OPEN', 'Invoice published')} disabled={changeStatus.isPending}>
                <CheckCircle2 className="size-4" /> Publish
              </Button>
            )}
            {canManage && invoice.is_editable && (
              <Button variant="outline" onClick={() => setEditOpen(true)}>
                <Pencil className="size-4" /> Edit
              </Button>
            )}
            {canManage && invoice.status !== 'CANCELLED' && !invoice.has_payments && (
              <Button variant="outline" className="text-destructive" onClick={() => setCancelOpen(true)}>
                <Ban className="size-4" /> Cancel invoice
              </Button>
            )}
          </>
        }
      />

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <SummaryCard label="Invoice amount" value={formatMoney(invoice.total_amount, invoice.currency)} />
        <SummaryCard label="Received" value={formatMoney(invoice.amount_received, invoice.currency)} tone="success" />
        <SummaryCard
          label="Outstanding"
          value={formatMoney(invoice.outstanding_amount, invoice.currency)}
          tone={invoice.status === 'OVERDUE' ? 'danger' : undefined}
          footer={
            invoice.status !== 'DRAFT' && invoice.status !== 'CANCELLED' ? (
              <div className="space-y-1.5">
                <div
                  role="progressbar"
                  aria-label="Percentage received"
                  aria-valuenow={percentReceived}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="h-1.5 overflow-hidden rounded-full bg-muted"
                >
                  <div className="h-full rounded-full bg-success" style={{ width: `${percentReceived}%` }} />
                </div>
                <p className="text-xs text-muted-foreground">{percentReceived}% received</p>
              </div>
            ) : null
          }
        />
      </div>

      <LifecycleTimeline invoiceId={invoice.id} />

      {invoice.has_payments && (
        <p className="mb-6 rounded-lg bg-muted px-4 py-3 text-sm text-muted-foreground">
          Payments are recorded against this invoice, so it can no longer be cancelled, and its number, currency,
          exporter and buyer are locked.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Invoice details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3 text-sm">
              <Detail label="Exporter">{invoice.exporter_name}</Detail>
              <Detail label="Buyer">{invoice.buyer_name}</Detail>
              <Detail label="Buyer country">{invoice.buyer_country}</Detail>
              <Detail label="Invoice date">{formatDate(invoice.invoice_date)}</Detail>
              <Detail label="Due date">
                {formatDate(invoice.due_date)} <DueHint invoice={invoice} />
              </Detail>
              <Detail label="Currency">{invoice.currency}</Detail>
              <Detail label="Payment terms">{invoice.payment_terms ?? '—'}</Detail>
              <Detail label="Description">{invoice.description ?? '—'}</Detail>
              <Detail label="Last updated">{formatDateTime(invoice.updated_at)}</Detail>
            </dl>
          </CardContent>
        </Card>

        <Card className="gap-0 py-0 lg:col-span-2">
          <CardHeader className="border-b py-4">
            <CardTitle>Payment history</CardTitle>
          </CardHeader>
          {invoice.payments.length === 0 ? (
            <EmptyState
              icon={Wallet}
              title="No payments allocated yet"
              description="Payments appear here once they are reconciled against this invoice."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead>Transaction</TableHead>
                  <TableHead>Sender</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Allocated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoice.payments.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.transaction_reference}</TableCell>
                    <TableCell>{p.sender_name}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDate(p.transaction_date)}</TableCell>
                    <TableCell>
                      <StatusBadge
                        label={p.allocation_type === 'AUTO' ? 'Automatic' : 'Manual'}
                        tone={p.allocation_type === 'AUTO' ? 'neutral' : 'info'}
                      />
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">
                      {formatMoney(p.allocated_amount, p.currency)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
      </div>

      <InvoiceFormSheet open={editOpen} onOpenChange={setEditOpen} invoice={invoice} />

      <AlertDialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel invoice {invoice.invoice_number}?</AlertDialogTitle>
            <AlertDialogDescription>
              The invoice will be marked as cancelled and can no longer be edited or receive payments. This is recorded
              in the audit log.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={changeStatus.isPending}>Keep invoice</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={changeStatus.isPending}
              onClick={() => void run('CANCELLED', `Invoice ${invoice.invoice_number} cancelled`)}
            >
              {changeStatus.isPending && <Loader2 className="size-4 animate-spin" />}
              Cancel invoice
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function BackLink() {
  return (
    <Link
      to="/invoices"
      className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-4" /> All invoices
    </Link>
  )
}

function SummaryCard({
  label,
  value,
  tone,
  footer,
}: {
  label: string
  value: string
  tone?: 'success' | 'danger'
  footer?: ReactNode
}) {
  return (
    <Card>
      <CardContent className="space-y-2">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p
          className={cn(
            'text-2xl font-semibold tracking-tight tabular-nums',
            tone === 'success' && 'text-success',
            tone === 'danger' && 'text-destructive',
            !tone && 'text-navy',
          )}
        >
          {value}
        </p>
        {footer}
      </CardContent>
    </Card>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  )
}

function DueHint({ invoice }: { invoice: InvoiceDetail }) {
  if (invoice.status === 'PAID' || invoice.status === 'CANCELLED' || invoice.status === 'DRAFT') return null
  const days = differenceInCalendarDays(parseISO(invoice.due_date), new Date())
  if (days < 0) return <span className="text-destructive">({-days}d overdue)</span>
  if (days === 0) return <span className="text-warning">(due today)</span>
  return <span className="font-normal text-muted-foreground">(in {days}d)</span>
}

function DetailSkeleton() {
  return (
    <div role="status" aria-label="Loading invoice" className="space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="h-64" />
    </div>
  )
}
