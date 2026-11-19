import { z } from 'zod'

import { SUPPORTED_CURRENCIES } from '@/types/invoice'

// Money stays a decimal *string* end to end: positive, at most 16 integer digits and 2 decimals.
const MONEY_PATTERN = /^\d{1,16}(\.\d{1,2})?$/

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Select a date')

export const invoiceFormSchema = z
  .object({
    invoice_number: z.string().trim().min(1, 'Invoice number is required').max(64, 'Max 64 characters'),
    exporter_id: z.string().min(1, 'Select an exporter'),
    buyer_name: z.string().trim().min(1, 'Buyer name is required').max(255, 'Max 255 characters'),
    buyer_country: z.string().trim().min(1, 'Buyer country is required').max(100, 'Max 100 characters'),
    invoice_date: isoDate,
    due_date: isoDate,
    currency: z.enum(SUPPORTED_CURRENCIES, { message: 'Select a currency' }),
    total_amount: z
      .string()
      .trim()
      .min(1, 'Amount is required')
      .regex(MONEY_PATTERN, 'Enter a valid amount with up to 2 decimals')
      .refine((v) => Number(v) > 0, 'Amount must be greater than zero'),
    payment_terms: z.string().trim().max(100, 'Max 100 characters'),
    description: z.string().trim().max(2000, 'Max 2000 characters'),
  })
  .refine((v) => !v.invoice_date || !v.due_date || v.due_date >= v.invoice_date, {
    path: ['due_date'],
    message: 'Due date cannot be before the invoice date',
  })

export type InvoiceFormValues = z.infer<typeof invoiceFormSchema>

export const INVOICE_FORM_FIELDS = Object.keys(invoiceFormSchema.shape) as (keyof InvoiceFormValues)[]
