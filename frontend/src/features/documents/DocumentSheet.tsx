import { zodResolver } from '@hookform/resolvers/zod'
import { AlertTriangle, CheckCircle2, Loader2, ScanText, Sparkles, ThumbsDown, WifiOff } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'

import { AiLabel } from '@/components/common/AiLabel'
import { ErrorState } from '@/components/common/ErrorState'
import { StatusBadge, type StatusTone } from '@/components/common/StatusBadge'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useAIStatus } from '@/features/copilot/hooks'
import { getErrorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { documentReviewSchema, type DocumentReviewValues } from '@/schemas/document'
import { DOCUMENT_TYPES, FIELD_KEYS, type DocumentDetail, type DocumentExplanation, type FieldKey, type FieldValues } from '@/types/document'

import { useDocument, useExplainDocument, useExtractDocument, useVerifyDocument } from './hooks'
import { DOCUMENT_TYPE_LABELS, ExtractionBadge, FIELD_LABELS, QualityBadge, VerificationBadge } from './labels'

interface DocumentSheetProps {
  documentId: string | null
  onClose: () => void
}

export function DocumentSheet({ documentId, onClose }: DocumentSheetProps) {
  const { data, isPending, isError, error, refetch } = useDocument(documentId)
  return (
    <Sheet open={!!documentId} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle className="break-all">{data?.file_name ?? 'Document'}</SheetTitle>
          <SheetDescription>
            AI reads the document; a person checks and confirms the values. Nothing here creates an invoice or a payment.
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto p-4">
          {isError ? (
            <ErrorState error={error} onRetry={() => void refetch()} title="Could not load this document" />
          ) : isPending ? (
            <div role="status" aria-label="Loading document" className="space-y-3">
              <Skeleton className="h-8 w-56" />
              <Skeleton className="h-40" />
            </div>
          ) : (
            <DocumentBody key={data.id} doc={data} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function DocumentBody({ doc }: { doc: DocumentDetail }) {
  const ai = useAIStatus()
  const extract = useExtractDocument(doc.id)
  const [extractError, setExtractError] = useState<string | null>(null)

  const runExtraction = () => {
    setExtractError(null)
    extract.mutate(undefined, {
      onSuccess: () => toast.success('Extraction finished. Please review the values.'),
      onError: (e) => setExtractError(getErrorMessage(e)),
    })
  }

  const finished = doc.verification_status === 'VERIFIED' || doc.verification_status === 'REJECTED'

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <VerificationBadge status={doc.verification_status} />
        <ExtractionBadge status={doc.extraction_status} />
        <span className="text-sm text-muted-foreground">
          {DOCUMENT_TYPE_LABELS[doc.document_type]}
          {doc.invoice_number && <> · invoice {doc.invoice_number}</>} · uploaded {formatDateTime(doc.created_at)}
          {doc.uploaded_by_name && <> by {doc.uploaded_by_name}</>}
        </span>
      </div>

      {extract.isPending ? (
        <div role="status" className="flex items-start gap-3 rounded-lg border bg-primary/5 p-4 text-sm">
          <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-primary" />
          <div>
            <p className="font-medium text-navy">Reading the document with the local AI model…</p>
            <p className="text-muted-foreground">This can take up to a minute on a laptop. You can keep this panel open.</p>
          </div>
        </div>
      ) : (
        !finished &&
        doc.extraction_status !== 'COMPLETED' && (
          <ExtractPrompt
            failed={doc.extraction_status === 'FAILED'}
            aiOffline={ai.data?.available === false}
            error={extractError}
            onRun={runExtraction}
          />
        )
      )}

      {doc.extraction && !extract.isPending && (
        <>
          {finished && doc.confirmation ? <ConfirmationPanel doc={doc} /> : <ReviewForm doc={doc} onRerun={runExtraction} aiOffline={ai.data?.available === false} />}
          <ExplainPanel doc={doc} />
        </>
      )}
    </div>
  )
}

function ExtractPrompt({
  failed,
  aiOffline,
  error,
  onRun,
}: {
  failed: boolean
  aiOffline: boolean
  error: string | null
  onRun: () => void
}) {
  return (
    <div className="space-y-3 rounded-lg border bg-muted/40 p-4">
      <p className="text-sm">
        {failed
          ? 'The last extraction did not complete. You can try again.'
          : 'This document has not been read yet. The local AI model will pull out the invoice details for you to review.'}
      </p>
      {aiOffline && (
        <p className="flex items-start gap-2 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
          <WifiOff className="mt-0.5 size-4 shrink-0" />
          The local AI service (Ollama) looks offline. Start it, then run the extraction.
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <Button onClick={onRun}>
        <ScanText className="size-4" /> {failed ? 'Try extraction again' : 'Run AI extraction'}
      </Button>
    </div>
  )
}

const TONE_FOR_FINDING: Record<string, StatusTone> = { MATCH: 'success', MISMATCH: 'danger', NOT_COMPARABLE: 'neutral' }

function ReviewForm({ doc, onRerun, aiOffline }: { doc: DocumentDetail; onRerun: () => void; aiOffline: boolean }) {
  const extraction = doc.extraction!
  const verify = useVerifyDocument(doc.id)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const initial: DocumentReviewValues = {
    document_type: extraction.fields.document_type as DocumentReviewValues['document_type'] ?? '',
    invoice_number: extraction.fields.invoice_number ?? '',
    exporter_name: extraction.fields.exporter_name ?? '',
    buyer_name: extraction.fields.buyer_name ?? '',
    buyer_country: extraction.fields.buyer_country ?? '',
    currency: extraction.fields.currency ?? '',
    invoice_amount: extraction.fields.invoice_amount ?? '',
    invoice_date: extraction.fields.invoice_date ?? '',
    due_date: extraction.fields.due_date ?? '',
    note: '',
  }
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<DocumentReviewValues>({ resolver: zodResolver(documentReviewSchema), defaultValues: initial })
  const current = watch()

  const toPayload = (v: DocumentReviewValues): FieldValues => {
    const out = {} as FieldValues
    for (const key of FIELD_KEYS) {
      const value = (v[key] ?? '').toString().trim()
      out[key] = value === '' ? null : key === 'currency' ? value.toUpperCase() : value
    }
    return out
  }

  const confirm = handleSubmit((values) => {
    setServerError(null)
    verify.mutate(
      { decision: 'VERIFIED', fields: toPayload(values), note: values.note || undefined },
      {
        onSuccess: () => toast.success('Document confirmed'),
        onError: (e) => setServerError(getErrorMessage(e)),
      },
    )
  })

  const reject = () =>
    verify.mutate(
      { decision: 'REJECTED', note: current.note || undefined },
      {
        onSuccess: () => {
          toast.success('Document rejected')
          setRejectOpen(false)
        },
        onError: (e) => {
          setRejectOpen(false)
          setServerError(getErrorMessage(e))
        },
      },
    )

  return (
    <form onSubmit={confirm} noValidate className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-navy">Review the extracted values</h3>
        <Button type="button" variant="ghost" size="sm" onClick={onRerun} disabled={aiOffline}>
          <ScanText className="size-4" /> Re-run extraction
        </Button>
      </div>

      {extraction.truncated && (
        <p className="flex items-start gap-2 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> This document was long, so only the first part was read. Check every value.
        </p>
      )}
      {extraction.issues.length > 0 && (
        <ul className="space-y-1 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
          {extraction.issues.map((issue) => (
            <li key={issue.field}>
              The AI gave an unusable value for <strong>{FIELD_LABELS[issue.field as FieldKey] ?? issue.field}</strong> ({issue.message}), so it was left blank.
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-muted-foreground">
        “Found in document” means the value appears in the document text. The AI's own confidence is only an estimate
        and is not proof that a value is right.
      </p>

      <div className="space-y-3">
        {FIELD_KEYS.map((key) => {
          const quality = extraction.quality[key]
          const edited = (current[key] ?? '') !== (initial[key as keyof DocumentReviewValues] ?? '')
          const estimate = extraction.llm_confidence[key]
          const error = errors[key as keyof DocumentReviewValues]?.message
          return (
            <div key={key} className="space-y-1.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Label htmlFor={`f-${key}`}>{FIELD_LABELS[key]}</Label>
                <span className="flex items-center gap-2">
                  {edited ? <StatusBadge label="Edited by you" tone="info" /> : <QualityBadge quality={quality} />}
                  {estimate !== undefined && !edited && (
                    <span className="text-xs text-muted-foreground" title="The model's own estimate, not a probability">
                      AI estimate {Math.round(estimate * 100)}%
                    </span>
                  )}
                </span>
              </div>
              {key === 'document_type' ? (
                <NativeSelect id={`f-${key}`} {...register('document_type')}>
                  <option value="">Not set</option>
                  {DOCUMENT_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {DOCUMENT_TYPE_LABELS[t]}
                    </option>
                  ))}
                </NativeSelect>
              ) : (
                <Input
                  id={`f-${key}`}
                  type={key === 'invoice_date' || key === 'due_date' ? 'date' : 'text'}
                  inputMode={key === 'invoice_amount' ? 'decimal' : undefined}
                  aria-invalid={!!error}
                  {...register(key)}
                />
              )}
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
          )
        })}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="review-note">Note (optional)</Label>
        <Textarea id="review-note" rows={2} maxLength={500} {...register('note')} />
      </div>

      {serverError && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {serverError}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t pt-4">
        <Button type="submit" disabled={verify.isPending}>
          {verify.isPending ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
          Confirm these values
        </Button>
        <Button type="button" variant="outline" className="text-destructive" onClick={() => setRejectOpen(true)} disabled={verify.isPending}>
          <ThumbsDown className="size-4" /> Reject document
        </Button>
      </div>

      <AlertDialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this document?</AlertDialogTitle>
            <AlertDialogDescription>
              It will be marked as rejected (for example, the wrong file or unreadable). This is recorded in the audit log.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={verify.isPending}>Keep reviewing</AlertDialogCancel>
            <Button variant="destructive" onClick={reject} disabled={verify.isPending}>
              {verify.isPending && <Loader2 className="size-4 animate-spin" />}
              Reject document
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  )
}

function ConfirmationPanel({ doc }: { doc: DocumentDetail }) {
  const c = doc.confirmation!
  const verified = c.decision === 'VERIFIED'
  return (
    <section className="space-y-3 rounded-lg border p-4" aria-label="Decision">
      <div className="flex items-start gap-2">
        {verified ? <CheckCircle2 className="mt-0.5 size-5 text-success" /> : <ThumbsDown className="mt-0.5 size-5 text-muted-foreground" />}
        <div>
          <p className="font-medium text-navy">
            {verified ? 'Confirmed' : 'Rejected'} by {c.by ?? 'a reviewer'}
            {c.at && <span className="font-normal text-muted-foreground"> · {formatDateTime(c.at)}</span>}
          </p>
          {c.note && <p className="text-sm text-muted-foreground">“{c.note}”</p>}
        </div>
      </div>
      {verified && (
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          {FIELD_KEYS.map((key) => {
            const confirmed = c.fields[key] ?? null
            const aiValue = doc.extraction?.fields[key] ?? null
            return (
              <div key={key} className="flex justify-between gap-3 border-b pb-1">
                <dt className="text-muted-foreground">{FIELD_LABELS[key]}</dt>
                <dd className="text-right font-medium">
                  {confirmed ?? '—'}
                  {confirmed !== aiValue && <span className="ml-1 text-xs font-normal text-primary">(corrected)</span>}
                </dd>
              </div>
            )
          })}
        </dl>
      )}
    </section>
  )
}

function ExplainPanel({ doc }: { doc: DocumentDetail }) {
  const explain = useExplainDocument(doc.id)
  const [result, setResult] = useState<DocumentExplanation | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setError(null)
    explain.mutate(undefined, { onSuccess: setResult, onError: (e) => setError(getErrorMessage(e)) })
  }

  return (
    <section className="space-y-3 border-t pt-4" aria-label="Document summary">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-navy">Summary and checks</h3>
        <Button type="button" variant="outline" size="sm" onClick={run} disabled={explain.isPending}>
          {explain.isPending ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
          {result ? 'Refresh summary' : 'Summarise with AI'}
        </Button>
      </div>
      {error && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {result && (
        <div className="space-y-3">
          <div className="space-y-2 rounded-lg border bg-muted/40 p-3 text-sm">
            <AiLabel generatedBy={result.generated_by} />
            <p>{result.summary}</p>
            {result.ai_note && <p className="text-xs text-muted-foreground">{result.ai_note}</p>}
          </div>
          {result.findings.length > 0 && (
            <ExplainFindings findings={result.findings} />
          )}
          <p className="text-xs text-muted-foreground">
            These checks compare values only. They are not legal or regulatory approval of the document.
          </p>
        </div>
      )}
    </section>
  )
}

function ExplainFindings({ findings }: { findings: DocumentExplanation['findings'] }): ReactNode {
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40 hover:bg-muted/40">
            <TableHead>Check</TableHead>
            <TableHead>Document</TableHead>
            <TableHead>Invoice</TableHead>
            <TableHead>Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {findings.map((f) => (
            <TableRow key={f.field}>
              <TableCell className="font-medium">{f.label}</TableCell>
              <TableCell>{f.document_value ?? '—'}</TableCell>
              <TableCell>{f.invoice_value}</TableCell>
              <TableCell>
                <StatusBadge
                  label={f.status === 'MATCH' ? 'Matches' : f.status === 'MISMATCH' ? 'Differs' : 'Not found'}
                  tone={TONE_FOR_FINDING[f.status]}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
