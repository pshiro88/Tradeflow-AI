import { StatusBadge, type StatusTone } from '@/components/common/StatusBadge'
import type { DocumentType, ExtractionStatus, FieldKey, FieldQuality, VerificationStatus } from '@/types/document'

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  COMMERCIAL_INVOICE: 'Commercial invoice',
  PACKING_LIST: 'Packing list',
  SHIPPING_BILL: 'Shipping bill',
  BILL_OF_LADING: 'Bill of lading / AWB',
  REMITTANCE_ADVICE: 'Remittance advice',
  OTHER: 'Other',
}

export const FIELD_LABELS: Record<FieldKey, string> = {
  document_type: 'Document type',
  invoice_number: 'Invoice number',
  exporter_name: 'Exporter',
  buyer_name: 'Buyer',
  buyer_country: 'Buyer country',
  currency: 'Currency',
  invoice_amount: 'Invoice amount',
  invoice_date: 'Invoice date',
  due_date: 'Due date',
}

const EXTRACTION: Record<ExtractionStatus, { label: string; tone: StatusTone }> = {
  NOT_STARTED: { label: 'Not extracted', tone: 'neutral' },
  IN_PROGRESS: { label: 'Processing', tone: 'info' },
  COMPLETED: { label: 'Extracted', tone: 'success' },
  FAILED: { label: 'Extraction failed', tone: 'danger' },
}

const VERIFICATION: Record<VerificationStatus, { label: string; tone: StatusTone }> = {
  NOT_UPLOADED: { label: 'Not uploaded', tone: 'neutral' },
  UPLOADED: { label: 'Uploaded', tone: 'neutral' },
  UNDER_REVIEW: { label: 'Under review', tone: 'info' },
  VERIFIED: { label: 'Verified', tone: 'success' },
  REJECTED: { label: 'Rejected', tone: 'danger' },
}

export function ExtractionBadge({ status }: { status: ExtractionStatus }) {
  return <StatusBadge label={EXTRACTION[status].label} tone={EXTRACTION[status].tone} />
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  return <StatusBadge label={VERIFICATION[status].label} tone={VERIFICATION[status].tone} />
}

export const VERIFICATION_LABELS = Object.fromEntries(Object.entries(VERIFICATION).map(([k, v]) => [k, v.label])) as Record<
  VerificationStatus,
  string
>

const QUALITY: Record<FieldQuality, { label: string; tone: StatusTone; hint: string }> = {
  FOUND_IN_TEXT: { label: 'Found in document', tone: 'success', hint: 'This value appears in the document text.' },
  NOT_FOUND_IN_TEXT: {
    label: 'Not in document: verify',
    tone: 'warning',
    hint: 'The AI returned this value but it does not appear in the document text. It may be wrong.',
  },
  INFERRED: { label: 'AI judgement', tone: 'neutral', hint: 'A classification by the AI, not text found in the document.' },
  MISSING: { label: 'Not found', tone: 'neutral', hint: 'The AI found nothing for this field. Fill it in if the document has it.' },
}

export function QualityBadge({ quality }: { quality: FieldQuality }) {
  const meta = QUALITY[quality]
  return (
    <span title={meta.hint}>
      <StatusBadge label={meta.label} tone={meta.tone} />
    </span>
  )
}
