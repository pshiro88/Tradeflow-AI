import { zodResolver } from '@hookform/resolvers/zod'
import { addDays, format } from 'date-fns'
import { Loader2, Lock } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { applyServerErrors } from '@/lib/form-errors'
import { INVOICE_FORM_FIELDS, invoiceFormSchema, type InvoiceFormValues } from '@/schemas/invoice'
import { SUPPORTED_CURRENCIES, type InvoiceDetail } from '@/types/invoice'

import { useBuyers, useCreateInvoice, useExporters, useUpdateInvoice } from './hooks'

interface InvoiceFormSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Pass an invoice to edit it; omit to create a new one. */
  invoice?: InvoiceDetail
  onSaved?: (invoice: InvoiceDetail) => void
}

export function InvoiceFormSheet({ open, onOpenChange, invoice, onSaved }: InvoiceFormSheetProps) {
  const isEdit = !!invoice
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full data-[side=right]:sm:max-w-xl">
        <SheetHeader className="border-b">
          <SheetTitle>{isEdit ? `Edit ${invoice.invoice_number}` : 'New export invoice'}</SheetTitle>
          <SheetDescription>
            {isEdit ? 'Update the invoice details.' : 'Create an invoice and start tracking its payments.'}
          </SheetDescription>
        </SheetHeader>
        {/* Mounted only while open, so the form always starts from fresh defaults. */}
        <InvoiceForm invoice={invoice} onDone={() => onOpenChange(false)} onSaved={onSaved} />
      </SheetContent>
    </Sheet>
  )
}

function defaultValues(invoice?: InvoiceDetail): InvoiceFormValues {
  if (invoice) {
    return {
      invoice_number: invoice.invoice_number,
      exporter_id: invoice.exporter_id,
      buyer_name: invoice.buyer_name,
      buyer_country: invoice.buyer_country,
      invoice_date: invoice.invoice_date,
      due_date: invoice.due_date,
      currency: invoice.currency as InvoiceFormValues['currency'],
      total_amount: invoice.total_amount,
      payment_terms: invoice.payment_terms ?? '',
      description: invoice.description ?? '',
    }
  }
  const today = new Date()
  return {
    invoice_number: '',
    exporter_id: '',
    buyer_name: '',
    buyer_country: '',
    invoice_date: format(today, 'yyyy-MM-dd'),
    due_date: format(addDays(today, 30), 'yyyy-MM-dd'),
    currency: 'USD',
    total_amount: '',
    payment_terms: 'Net 30',
    description: '',
  }
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="text-sm text-destructive">{message}</p> : null
}

function InvoiceForm({
  invoice,
  onDone,
  onSaved,
}: {
  invoice?: InvoiceDetail
  onDone: () => void
  onSaved?: (invoice: InvoiceDetail) => void
}) {
  const isEdit = !!invoice
  // Once payments are allocated, the fields that give those allocations meaning are frozen.
  const locked = !!invoice?.has_payments

  const exporters = useExporters()
  const buyers = useBuyers()
  const create = useCreateInvoice()
  const update = useUpdateInvoice(invoice?.id ?? '')

  const {
    register,
    handleSubmit,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<InvoiceFormValues>({ resolver: zodResolver(invoiceFormSchema), defaultValues: defaultValues(invoice) })

  const save = (status: 'DRAFT' | 'OPEN') =>
    handleSubmit(async (values) => {
      const body = { ...values, description: values.description || null, payment_terms: values.payment_terms || null }
      try {
        const saved = invoice ? await update.mutateAsync(body) : await create.mutateAsync({ ...body, status })
        toast.success(
          invoice ? `Invoice ${saved.invoice_number} updated` : `Invoice ${saved.invoice_number} created`,
        )
        onSaved?.(saved)
        onDone()
      } catch (error) {
        applyServerErrors(error, setError, { knownFields: INVOICE_FORM_FIELDS, conflictField: 'invoice_number' })
      }
    })

  const onBuyerNameChange = (value: string) => {
    // Picking an existing buyer fills in its country.
    const known = buyers.data?.find((b) => b.name.toLowerCase() === value.trim().toLowerCase())
    if (known) setValue('buyer_country', known.country, { shouldValidate: true })
  }

  return (
    <form onSubmit={save('OPEN')} noValidate className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {locked && (
          <p className="flex items-start gap-2 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">
            <Lock className="mt-0.5 size-4 shrink-0" />
            Payments are already recorded, so the invoice number, currency, exporter and buyer are locked. The amount
            cannot go below what has been received.
          </p>
        )}

        <div className="space-y-2">
          <Label htmlFor="invoice_number">Invoice number</Label>
          <Input
            id="invoice_number"
            placeholder="INV-1025"
            disabled={locked}
            aria-invalid={!!errors.invoice_number}
            {...register('invoice_number')}
          />
          <FieldError message={errors.invoice_number?.message} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="exporter_id">Exporter</Label>
          <NativeSelect id="exporter_id" disabled={locked} aria-invalid={!!errors.exporter_id} {...register('exporter_id')}>
            <option value="">{exporters.isPending ? 'Loading…' : 'Select exporter'}</option>
            {exporters.data?.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </NativeSelect>
          <FieldError message={errors.exporter_id?.message} />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="buyer_name">Buyer name</Label>
            <Input
              id="buyer_name"
              list="buyer-suggestions"
              autoComplete="off"
              disabled={locked}
              aria-invalid={!!errors.buyer_name}
              {...register('buyer_name', { onChange: (e) => onBuyerNameChange(e.target.value) })}
            />
            <datalist id="buyer-suggestions">
              {buyers.data?.map((b) => (
                <option key={b.id} value={b.name} />
              ))}
            </datalist>
            <FieldError message={errors.buyer_name?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="buyer_country">Buyer country</Label>
            <Input id="buyer_country" disabled={locked} aria-invalid={!!errors.buyer_country} {...register('buyer_country')} />
            <FieldError message={errors.buyer_country?.message} />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="invoice_date">Invoice date</Label>
            <Input id="invoice_date" type="date" aria-invalid={!!errors.invoice_date} {...register('invoice_date')} />
            <FieldError message={errors.invoice_date?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="due_date">Due date</Label>
            <Input id="due_date" type="date" aria-invalid={!!errors.due_date} {...register('due_date')} />
            <FieldError message={errors.due_date?.message} />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="currency">Currency</Label>
            <NativeSelect id="currency" disabled={locked} aria-invalid={!!errors.currency} {...register('currency')}>
              {SUPPORTED_CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </NativeSelect>
            <FieldError message={errors.currency?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="total_amount">Invoice amount</Label>
            <Input
              id="total_amount"
              inputMode="decimal"
              placeholder="10000.00"
              aria-invalid={!!errors.total_amount}
              {...register('total_amount')}
            />
            <FieldError message={errors.total_amount?.message} />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="payment_terms">Payment terms</Label>
          <Input id="payment_terms" placeholder="Net 30" aria-invalid={!!errors.payment_terms} {...register('payment_terms')} />
          <FieldError message={errors.payment_terms?.message} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea id="description" rows={3} aria-invalid={!!errors.description} {...register('description')} />
          <FieldError message={errors.description?.message} />
        </div>

        {errors.root && (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {errors.root.message}
          </p>
        )}
      </div>

      <SheetFooter className="border-t sm:flex-row sm:justify-end">
        <Button type="button" variant="ghost" onClick={onDone} disabled={isSubmitting}>
          Cancel
        </Button>
        {!isEdit && (
          <Button type="button" variant="outline" onClick={save('DRAFT')} disabled={isSubmitting}>
            Save as draft
          </Button>
        )}
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting && <Loader2 className="size-4 animate-spin" />}
          {isEdit ? 'Save changes' : 'Create invoice'}
        </Button>
      </SheetFooter>
    </form>
  )
}
