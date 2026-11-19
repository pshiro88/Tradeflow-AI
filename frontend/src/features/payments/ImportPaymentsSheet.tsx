import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Loader2,
  RotateCcw,
  UploadCloud,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { useDropzone, type FileRejection } from 'react-dropzone'
import { toast } from 'sonner'

import { StatusBadge, type StatusTone } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getErrorMessage } from '@/lib/api'
import { downloadBlob } from '@/lib/download'
import { cn } from '@/lib/utils'
import { downloadImportErrorReport } from '@/services/payments'
import type { ImportBatchDetail, ImportErrorCategory } from '@/types/payment'

import { useImportPayments } from './hooks'

const MAX_FILE_MB = 10
const TEMPLATE_CSV =
  'transaction_reference,payment_reference,sender_name,currency,amount,transaction_date,bank_reference\n' +
  'TXN-3001,INV-1021,Thames Gate Wholesale Ltd,GBP,5200.00,2026-11-15,SIM-SWIFT-000001\n'

const CATEGORY_META: Record<ImportErrorCategory, { label: string; tone: StatusTone }> = {
  VALIDATION: { label: 'Invalid', tone: 'danger' },
  DUPLICATE_IN_FILE: { label: 'Repeated in file', tone: 'warning' },
  DUPLICATE_EXISTING: { label: 'Already imported', tone: 'warning' },
}

function describeRejection(rejections: FileRejection[]): string {
  const code = rejections[0]?.errors[0]?.code
  if (code === 'file-too-large') return `That file is larger than ${MAX_FILE_MB} MB.`
  if (code === 'file-invalid-type') return 'Only .csv files are supported.'
  if (code === 'too-many-files') return 'Please upload one file at a time.'
  return 'That file cannot be uploaded.'
}

interface ImportPaymentsSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ImportPaymentsSheet({ open, onOpenChange }: ImportPaymentsSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle>Import bank transactions</SheetTitle>
          <SheetDescription>
            Upload a CSV of received payments. Valid rows are imported; problem rows are reported so you can fix them.
          </SheetDescription>
        </SheetHeader>
        {/* Mounted only while open so each session starts at the upload step. */}
        <ImportFlow />
      </SheetContent>
    </Sheet>
  )
}

function ImportFlow() {
  const importMutation = useImportPayments()
  const [result, setResult] = useState<ImportBatchDetail | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    accept: { 'text/csv': ['.csv'], 'application/vnd.ms-excel': ['.csv'] },
    maxSize: MAX_FILE_MB * 1024 * 1024,
    multiple: false,
    noClick: true, // the explicit "Choose file" button opens the picker
    disabled: importMutation.isPending,
    onDropRejected: (rejections) => setUploadError(describeRejection(rejections)),
    onDropAccepted: ([file]) => {
      setUploadError(null)
      importMutation.mutate(file, {
        onSuccess: (batch) => {
          setResult(batch)
          toast.success(`Imported ${batch.accepted_rows} of ${batch.total_rows} transactions`)
        },
        onError: (error) => setUploadError(getErrorMessage(error, 'The import failed. Please try again.')),
      })
    },
  })

  const downloadTemplate = () => downloadBlob(new Blob([TEMPLATE_CSV], { type: 'text/csv' }), 'payments-template.csv')

  const downloadErrors = async () => {
    if (!result) return
    setDownloading(true)
    try {
      downloadBlob(await downloadImportErrorReport(result.id), `import-errors-${result.id.slice(0, 8)}.csv`)
    } catch (error) {
      toast.error(getErrorMessage(error))
    } finally {
      setDownloading(false)
    }
  }

  if (result) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-4">
        <ImportSummary batch={result} onDownload={downloadErrors} downloading={downloading} />
        <Button variant="outline" className="self-start" onClick={() => setResult(null)}>
          <RotateCcw className="size-4" /> Import another file
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-4 p-4">
      <div
        {...getRootProps()}
        className={cn(
          'flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors',
          isDragActive ? 'border-primary bg-primary/5' : 'border-border bg-muted/30',
          importMutation.isPending && 'opacity-70',
        )}
      >
        <input {...getInputProps()} aria-label="CSV file" />
        {importMutation.isPending ? (
          <>
            <Loader2 className="size-9 animate-spin text-primary" />
            <p className="font-medium text-navy" role="status">
              Validating and importing…
            </p>
          </>
        ) : (
          <>
            <UploadCloud className="size-9 text-primary" />
            <div>
              <p className="font-medium text-navy">{isDragActive ? 'Drop the file to upload' : 'Drag a CSV file here'}</p>
              <p className="text-sm text-muted-foreground">or choose one from your computer (max {MAX_FILE_MB} MB)</p>
            </div>
            <Button type="button" onClick={open}>
              Choose file
            </Button>
          </>
        )}
      </div>

      {uploadError && (
        <p role="alert" className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <XCircle className="mt-0.5 size-4 shrink-0" /> {uploadError}
        </p>
      )}

      <div className="rounded-lg border bg-card p-4 text-sm">
        <p className="mb-2 font-medium text-navy">Expected columns</p>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Required:</span> transaction_reference, sender_name, currency,
          amount, transaction_date.
          <br />
          <span className="font-medium text-foreground">Optional:</span> payment_reference, bank_reference.
        </p>
        <p className="mt-2 text-muted-foreground">
          Dates use YYYY-MM-DD, amounts are plain numbers with up to 2 decimals, and the currency must be USD, EUR, GBP,
          AED or INR.
        </p>
        <Button variant="link" className="mt-1 h-auto px-0" onClick={downloadTemplate}>
          <FileSpreadsheet className="size-4" /> Download CSV template
        </Button>
      </div>
    </div>
  )
}

function ImportSummary({
  batch,
  onDownload,
  downloading,
}: {
  batch: ImportBatchDetail
  onDownload: () => void
  downloading: boolean
}) {
  const problems = batch.rejected_rows + batch.duplicate_rows
  return (
    <>
      <div className="flex items-center gap-2">
        {problems === 0 ? (
          <CheckCircle2 className="size-5 text-success" />
        ) : (
          <AlertTriangle className="size-5 text-warning" />
        )}
        <p className="font-medium text-navy">
          {batch.file_name}{' '}
          <span className="font-normal text-muted-foreground">
            {problems === 0 ? 'imported without problems' : 'imported with some rows skipped'}
          </span>
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Import summary">
        <Stat label="Rows in file" value={batch.total_rows} />
        <Stat label="Imported" value={batch.accepted_rows} tone="success" />
        <Stat label="Duplicates" value={batch.duplicate_rows} tone={batch.duplicate_rows ? 'warning' : undefined} />
        <Stat label="Rejected" value={batch.rejected_rows} tone={batch.rejected_rows ? 'danger' : undefined} />
      </div>

      {batch.errors.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium text-navy">Rows that were not imported ({batch.errors.length})</p>
            <Button variant="outline" size="sm" onClick={onDownload} disabled={downloading}>
              {downloading ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
              Download error report
            </Button>
          </div>
          <div className="max-h-96 overflow-y-auto rounded-lg border">
            <Table>
              <TableHeader className="sticky top-0 bg-card">
                <TableRow>
                  <TableHead className="w-14">Line</TableHead>
                  <TableHead>Transaction</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {batch.errors.map((err) => {
                  const meta = CATEGORY_META[err.category]
                  return (
                    <TableRow key={err.row}>
                      <TableCell className="text-muted-foreground tabular-nums">{err.row}</TableCell>
                      <TableCell className="font-medium">{err.transaction_reference ?? '—'}</TableCell>
                      <TableCell>
                        <StatusBadge label={meta.label} tone={meta.tone} />
                      </TableCell>
                      <TableCell className="text-sm whitespace-normal">
                        {err.issues.map((issue, i) => (
                          <p key={i}>
                            <span className="text-muted-foreground">{issue.field}:</span> {issue.message}
                          </p>
                        ))}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'success' | 'warning' | 'danger' }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          'text-2xl font-semibold tabular-nums',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-destructive',
          !tone && 'text-navy',
        )}
      >
        {value}
      </p>
    </div>
  )
}
