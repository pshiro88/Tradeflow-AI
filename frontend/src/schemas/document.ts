import { z } from 'zod'

import { DOCUMENT_TYPES } from '@/types/document'

const emptyOr = (pattern: RegExp, message: string) => z.string().trim().refine((v) => v === '' || pattern.test(v), message)

/** A reviewer's confirmed values. Empty string means "no value" and is sent to the API as null. */
export const documentReviewSchema = z.object({
  document_type: z.union([z.enum(DOCUMENT_TYPES), z.literal('')]),
  invoice_number: z.string().trim().max(64, 'Max 64 characters'),
  exporter_name: z.string().trim().max(255, 'Max 255 characters'),
  buyer_name: z.string().trim().max(255, 'Max 255 characters'),
  buyer_country: z.string().trim().max(100, 'Max 100 characters'),
  currency: emptyOr(/^[A-Za-z]{3}$/, 'Use a 3-letter code such as USD'),
  invoice_amount: z
    .string()
    .trim()
    .refine((v) => v === '' || (/^\d{1,16}(\.\d{1,2})?$/.test(v) && Number(v) > 0), 'Enter an amount above zero with up to 2 decimals'),
  invoice_date: emptyOr(/^\d{4}-\d{2}-\d{2}$/, 'Use a valid date'),
  due_date: emptyOr(/^\d{4}-\d{2}-\d{2}$/, 'Use a valid date'),
  note: z.string().trim().max(500, 'Max 500 characters'),
})

export type DocumentReviewValues = z.infer<typeof documentReviewSchema>
