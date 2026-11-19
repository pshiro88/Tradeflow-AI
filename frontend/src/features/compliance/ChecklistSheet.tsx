import { AlertTriangle, CheckCircle2, FileText, Loader2, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { ErrorState } from '@/components/common/ErrorState'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { VerificationBadge } from '@/features/documents/labels'
import { getErrorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Checklist, ChecklistItem } from '@/types/compliance'

import { useChecklist, useRecordCheck } from './hooks'

interface ChecklistSheetProps {
  invoiceId: string | null
  onClose: () => void
}

export function ChecklistSheet({ invoiceId, onClose }: ChecklistSheetProps) {
  const { data, isPending, isError, error, refetch } = useChecklist(invoiceId)
  return (
    <Sheet open={!!invoiceId} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle>{data ? `Documents for ${data.invoice_number}` : 'Document checklist'}</SheetTitle>
          <SheetDescription>Which documents are on file, whether they are verified, and whether they agree with the invoice.</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto p-4">
          {isError ? (
            <ErrorState error={error} onRetry={() => void refetch()} title="Could not load the checklist" />
          ) : isPending ? (
            <div role="status" aria-label="Loading checklist" className="space-y-3">
              <Skeleton className="h-20" />
              <Skeleton className="h-32" />
              <Skeleton className="h-32" />
            </div>
          ) : (
            <ChecklistBody checklist={data} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function ChecklistBody({ checklist }: { checklist: Checklist }) {
  const { summary, readiness } = checklist
  const percent = summary.required_total ? Math.round((summary.verified / summary.required_total) * 100) : 0
  return (
    <div className="space-y-5">
      <section className="space-y-3 rounded-lg border p-4" aria-label="Progress">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium text-navy">
            {summary.verified} of {summary.required_total} required documents verified
          </p>
          <Link to={`/invoices/${checklist.invoice_id}`} className="text-sm text-primary hover:underline">
            View invoice
          </Link>
        </div>
        <div
          role="progressbar"
          aria-label="Required documents verified"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-2 overflow-hidden rounded-full bg-muted"
        >
          <div className="h-full rounded-full bg-success" style={{ width: `${percent}%` }} />
        </div>
        <p className="text-sm text-muted-foreground">
          {summary.missing > 0 && <>{summary.missing} missing or rejected · </>}
          {summary.under_review + summary.uploaded > 0 && <>{summary.under_review + summary.uploaded} awaiting review · </>}
          {summary.flagged > 0 ? <span className="font-medium text-warning">{summary.flagged} differ from the invoice</span> : 'no differences from the invoice'}
        </p>
      </section>

      <section
        aria-label="Export filing readiness"
        className={cn('rounded-lg border p-4 text-sm', readiness.ready ? 'border-success/30 bg-success/5' : 'bg-muted/40')}
      >
        <p className="flex items-center gap-2 font-medium text-navy">
          {readiness.ready ? <CheckCircle2 className="size-5 text-success" /> : <ShieldAlert className="size-5 text-muted-foreground" />}
          {readiness.ready ? 'Ready for export filing (simulated)' : 'Not ready for export filing yet (simulated)'}
        </p>
        {!readiness.ready && (
          <ul className="mt-2 list-disc space-y-0.5 pl-6 text-muted-foreground">
            {readiness.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted-foreground">{checklist.disclaimer}</p>
      </section>

      <ul className="space-y-3">
        {checklist.items.map((item) => (
          <ItemCard key={item.document_type} item={item} invoiceId={checklist.invoice_id} />
        ))}
      </ul>
    </div>
  )
}

function ItemCard({ item, invoiceId }: { item: ChecklistItem; invoiceId: string }) {
  const record = useRecordCheck(invoiceId)
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<'UNDER_REVIEW' | 'VERIFIED' | 'REJECTED'>('VERIFIED')
  const [remarks, setRemarks] = useState('')
  const [error, setError] = useState<string | null>(null)
  const mismatches = item.findings.filter((f) => f.status === 'MISMATCH')

  const submit = () => {
    setError(null)
    record.mutate(
      { document_type: item.document_type, status, remarks: remarks.trim() || undefined },
      {
        onSuccess: () => {
          toast.success(`${item.label} review recorded`)
          setOpen(false)
          setRemarks('')
        },
        onError: (e) => setError(getErrorMessage(e)),
      },
    )
  }

  return (
    <li className="space-y-3 rounded-lg border bg-card p-4" aria-label={item.label}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-navy">{item.label}</p>
          <p className="text-xs text-muted-foreground">{item.required ? 'Required' : (item.requirement_note ?? 'Optional')}</p>
        </div>
        <div className="flex items-center gap-2">
          {item.has_mismatch && <StatusBadge label="Differs from invoice" tone="warning" />}
          <VerificationBadge status={item.status} />
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        {item.source === 'MANUAL' ? (
          <>
            Manual review by {item.reviewed_by ?? 'a reviewer'}
            {item.reviewed_at && <> · {formatDateTime(item.reviewed_at)}</>}
            {item.remarks && <>: “{item.remarks}”</>}
          </>
        ) : item.source === 'DOCUMENT' ? (
          'Status comes from the uploaded document.'
        ) : (
          'Nothing uploaded or reviewed yet.'
        )}
      </p>

      {item.documents.length > 0 && (
        <ul className="space-y-1 text-sm">
          {item.documents.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2">
              <Link to={`/documents?q=${encodeURIComponent(d.file_name)}`} className="flex min-w-0 items-center gap-1.5 text-primary hover:underline">
                <FileText className="size-4 shrink-0" />
                <span className="truncate">{d.file_name}</span>
              </Link>
              <VerificationBadge status={d.verification_status} />
            </li>
          ))}
        </ul>
      )}

      {item.findings.length > 0 &&
        (mismatches.length > 0 ? (
          <div className="space-y-1.5 rounded-md bg-warning/10 p-3 text-sm" role="alert">
            <p className="flex items-center gap-1.5 font-medium text-warning">
              <AlertTriangle className="size-4" /> {mismatches.length} difference{mismatches.length === 1 ? '' : 's'} from the invoice
              {item.compared_document && <span className="font-normal text-muted-foreground"> (in {item.compared_document})</span>}
            </p>
            <ul className="space-y-0.5">
              {mismatches.map((m) => (
                <li key={m.field}>
                  <span className="font-medium">{m.label}:</span> {m.message}
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">A person should check these. They are flags, not a ruling.</p>
          </div>
        ) : (
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4 text-success" />
            {item.findings.filter((f) => f.status === 'MATCH').length} checked values agree with the invoice
          </p>
        ))}

      {open ? (
        <div className="space-y-3 rounded-md border bg-muted/30 p-3">
          <div className="space-y-1.5">
            <Label htmlFor={`status-${item.document_type}`}>Your review</Label>
            <NativeSelect id={`status-${item.document_type}`} value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
              <option value="VERIFIED">Verified</option>
              <option value="UNDER_REVIEW">Under review</option>
              <option value="REJECTED">Rejected</option>
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`remarks-${item.document_type}`}>
              Remarks{item.documents.length === 0 && status === 'VERIFIED' ? ' (required: say how it was verified)' : ' (optional)'}
            </Label>
            <Textarea id={`remarks-${item.document_type}`} rows={2} maxLength={500} value={remarks} onChange={(e) => setRemarks(e.target.value)} />
          </div>
          {error && (
            <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <Button size="sm" onClick={submit} disabled={record.isPending}>
              {record.isPending && <Loader2 className="size-4 animate-spin" />} Save review
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={record.isPending}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
          Record a review
        </Button>
      )}
    </li>
  )
}
