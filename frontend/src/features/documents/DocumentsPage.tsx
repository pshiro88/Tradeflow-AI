import { FileSearch, FileText, Loader2, Search, UploadCloud, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useDropzone, type FileRejection } from 'react-dropzone'
import { toast } from 'sonner'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { PageHeader } from '@/components/common/PageHeader'
import { Pagination } from '@/components/common/Pagination'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useInvoices } from '@/features/invoices/hooks'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useUrlParams } from '@/hooks/useUrlParams'
import { getErrorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { DOCUMENT_TYPES, type DocumentListParams, type DocumentType, type VerificationStatus } from '@/types/document'

import { DocumentSheet } from './DocumentSheet'
import { useDocuments, useUploadDocument } from './hooks'
import { DOCUMENT_TYPE_LABELS, ExtractionBadge, VERIFICATION_LABELS, VerificationBadge } from './labels'

const PAGE_SIZE = 10
const MAX_MB = 10
const VERIFICATION_FILTERS: VerificationStatus[] = ['UPLOADED', 'UNDER_REVIEW', 'VERIFIED', 'REJECTED']

function parseParams(sp: URLSearchParams): DocumentListParams {
  const type = sp.get('type')
  const status = sp.get('status')
  return {
    page: Math.max(1, Number(sp.get('page')) || 1),
    page_size: PAGE_SIZE,
    search: sp.get('q') || undefined,
    document_type: DOCUMENT_TYPES.includes(type as DocumentType) ? (type as DocumentType) : undefined,
    verification_status: VERIFICATION_FILTERS.includes(status as VerificationStatus) ? (status as VerificationStatus) : undefined,
  }
}

function describeRejection(rejections: FileRejection[]): string {
  const code = rejections[0]?.errors[0]?.code
  if (code === 'file-too-large') return `That file is larger than ${MAX_MB} MB.`
  if (code === 'file-invalid-type') return 'Only PDF files are supported.'
  return 'That file cannot be uploaded.'
}

export default function DocumentsPage() {
  const { searchParams, update, clear } = useUrlParams()
  const params = parseParams(searchParams)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState(params.search ?? '')
  const debouncedSearch = useDebouncedValue(searchInput)
  const { data, isPending, isError, error, refetch, isFetching } = useDocuments(params)

  useEffect(() => {
    if ((params.search ?? '') !== debouncedSearch.trim()) update({ q: debouncedSearch.trim() || undefined })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch])

  const hasFilters = !!(params.search || params.document_type || params.verification_status)
  const clearFilters = () => {
    setSearchInput('')
    clear()
  }

  return (
    <>
      <PageHeader
        title="Documents"
        description="Upload trade documents, let the local AI read them, then check and confirm the values."
      />

      <UploadPanel onUploaded={(id) => setSelectedId(id)} />

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search documents"
              placeholder="Search file name or invoice"
              className="pl-8"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
          <NativeSelect
            aria-label="Filter by document type"
            className="w-48"
            value={params.document_type ?? ''}
            onChange={(e) => update({ type: e.target.value || undefined })}
          >
            <option value="">All types</option>
            {DOCUMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {DOCUMENT_TYPE_LABELS[t]}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label="Filter by verification status"
            className="w-44"
            value={params.verification_status ?? ''}
            onChange={(e) => update({ status: e.target.value || undefined })}
          >
            <option value="">All statuses</option>
            {VERIFICATION_FILTERS.map((s) => (
              <option key={s} value={s}>
                {VERIFICATION_LABELS[s]}
              </option>
            ))}
          </NativeSelect>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="size-4" /> Clear
            </Button>
          )}
        </div>

        {isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} title="Could not load documents" />
        ) : isPending ? (
          <div className="space-y-3 p-4" role="status" aria-label="Loading documents">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : data.total === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={FileSearch}
              title="No documents match your filters"
              action={
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState icon={FileText} title="No documents yet" description="Upload a text-based PDF above to get started." />
          )
        ) : (
          <>
            <div className={cn('transition-opacity', isFetching && 'opacity-60')}>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead>File</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Invoice</TableHead>
                    <TableHead>Extraction</TableHead>
                    <TableHead>Review</TableHead>
                    <TableHead>Uploaded</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((d) => (
                    <TableRow
                      key={d.id}
                      tabIndex={0}
                      className="cursor-pointer"
                      onClick={() => setSelectedId(d.id)}
                      onKeyDown={(e) => e.key === 'Enter' && setSelectedId(d.id)}
                    >
                      <TableCell className="font-medium">{d.file_name}</TableCell>
                      <TableCell>{DOCUMENT_TYPE_LABELS[d.document_type]}</TableCell>
                      <TableCell className="text-muted-foreground">{d.invoice_number ?? '—'}</TableCell>
                      <TableCell>
                        <ExtractionBadge status={d.extraction_status} />
                      </TableCell>
                      <TableCell>
                        <VerificationBadge status={d.verification_status} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatDateTime(d.created_at)}
                        {d.uploaded_by_name && <span className="block text-xs">{d.uploaded_by_name}</span>}
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

      <DocumentSheet documentId={selectedId} onClose={() => setSelectedId(null)} />
    </>
  )
}

function UploadPanel({ onUploaded }: { onUploaded: (documentId: string) => void }) {
  const upload = useUploadDocument()
  const [documentType, setDocumentType] = useState<DocumentType>('COMMERCIAL_INVOICE')
  const [invoiceId, setInvoiceId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const invoices = useInvoices({ page: 1, page_size: 100, sort_by: 'invoice_number', sort_dir: 'asc' })

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    maxSize: MAX_MB * 1024 * 1024,
    multiple: false,
    noClick: true,
    disabled: upload.isPending,
    onDropRejected: (r) => setError(describeRejection(r)),
    onDropAccepted: ([file]) => {
      setError(null)
      upload.mutate(
        { file, documentType, invoiceId: invoiceId || undefined },
        {
          onSuccess: (doc) => {
            toast.success(`Uploaded ${doc.file_name}`)
            onUploaded(doc.id)
          },
          onError: (e) => setError(getErrorMessage(e, 'The upload failed. Please try again.')),
        },
      )
    },
  })

  return (
    <Card className="mb-6 gap-4 p-4">
      <div className="grid gap-4 md:grid-cols-[1fr_1fr_2fr]">
        <div className="space-y-1.5">
          <Label htmlFor="doc-type">Document type</Label>
          <NativeSelect id="doc-type" value={documentType} onChange={(e) => setDocumentType(e.target.value as DocumentType)} disabled={upload.isPending}>
            {DOCUMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {DOCUMENT_TYPE_LABELS[t]}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="doc-invoice">Linked invoice (optional)</Label>
          <NativeSelect id="doc-invoice" value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)} disabled={upload.isPending}>
            <option value="">Not linked</option>
            {invoices.data?.items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.invoice_number} · {i.buyer_name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div
          {...getRootProps()}
          className={cn(
            'flex items-center justify-center gap-3 rounded-xl border-2 border-dashed px-4 py-5 text-sm transition-colors',
            isDragActive ? 'border-primary bg-primary/5' : 'bg-muted/30',
          )}
        >
          <input {...getInputProps()} aria-label="PDF file" />
          {upload.isPending ? (
            <span role="status" className="flex items-center gap-2 font-medium text-navy">
              <Loader2 className="size-5 animate-spin text-primary" /> Checking and uploading…
            </span>
          ) : (
            <>
              <UploadCloud className="size-6 shrink-0 text-primary" />
              <span className="text-muted-foreground">
                {isDragActive ? 'Drop the PDF here' : `Drag a text-based PDF here (max ${MAX_MB} MB) or`}
              </span>
              <Button type="button" size="sm" onClick={open}>
                Choose PDF
              </Button>
            </>
          )}
        </div>
      </div>
      {error && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Scanned or image-only PDFs are not supported yet. The file is checked and stored first; the AI only runs when you ask it to.
      </p>
    </Card>
  )
}
