import { Check, Circle, Clock, Minus } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { LifecycleState } from '@/types/compliance'

import { useLifecycle } from './hooks'

const STATE_STYLE: Record<LifecycleState, { icon: typeof Check; ring: string; text: string }> = {
  DONE: { icon: Check, ring: 'bg-success text-white', text: 'Done' },
  IN_PROGRESS: { icon: Clock, ring: 'bg-warning text-white', text: 'In progress' },
  PENDING: { icon: Circle, ring: 'border-2 border-border bg-card text-muted-foreground', text: 'Not yet' },
  NOT_APPLICABLE: { icon: Minus, ring: 'bg-muted text-muted-foreground', text: 'Not applicable' },
}

/**
 * Where an invoice is between "issued" and "ready for export filing". The last step is a simulated readiness
 * checklist: TradeFlow files nothing (no eBRC, no FIRA). Shows progress only, so every role may see it.
 */
export function LifecycleTimeline({ invoiceId }: { invoiceId: string }) {
  const { data, isPending, isError } = useLifecycle(invoiceId)

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Invoice progress</CardTitle>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <Skeleton className="h-24 w-full" role="status" aria-label="Loading progress" />
        ) : isError ? (
          <p className="text-sm text-muted-foreground">Progress is not available right now.</p>
        ) : (
          <>
            <ol aria-label="Invoice progress" className="grid gap-4 md:grid-cols-5">
              {data.steps.map((step, index) => {
                const style = STATE_STYLE[step.state]
                const Icon = style.icon
                return (
                  <li key={step.key} className="relative flex gap-3 md:flex-col md:gap-2" data-state={step.state}>
                    <div className="flex items-center md:w-full">
                      <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', style.ring)}>
                        <Icon className="size-4" aria-hidden />
                      </span>
                      {index < data.steps.length - 1 && (
                        <span aria-hidden className={cn('ml-2 hidden h-0.5 flex-1 md:block', step.state === 'DONE' ? 'bg-success/50' : 'bg-border')} />
                      )}
                    </div>
                    <div className="space-y-0.5 text-sm">
                      <p className="font-medium text-navy">
                        {step.label} <span className="sr-only">({style.text})</span>
                      </p>
                      {step.date && <p className="text-xs text-muted-foreground">{formatDate(step.date)}</p>}
                      <p className="text-xs text-muted-foreground">{step.detail}</p>
                    </div>
                  </li>
                )
              })}
            </ol>
            <p className="mt-4 text-xs text-muted-foreground">{data.note}</p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
