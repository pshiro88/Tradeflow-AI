import { BarChart3, Table2 } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface ChartCardProps {
  title: string
  description?: string
  /** Controls that scope only this card (e.g. a range selector). Shared filters live above all cards. */
  actions?: ReactNode
  chart: ReactNode
  /** The same data as an accessible table: every chart has a table twin. */
  table: ReactNode
  /** True while a refetch is in flight: the previous render stays visible, dimmed. */
  busy?: boolean
}

export function ChartCard({ title, description, actions, chart, table, busy }: ChartCardProps) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const bodyId = useId()

  return (
    <Card className="gap-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4">
        <div className="space-y-0.5">
          <h2 className="font-medium text-navy">{title}</h2>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        <div className="flex items-center gap-2">
          {actions}
          <div role="group" aria-label={`${title} view`} className="inline-flex rounded-lg border p-0.5">
            {(
              [
                ['chart', BarChart3, 'Chart'],
                ['table', Table2, 'Table'],
              ] as const
            ).map(([key, Icon, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={view === key}
                aria-controls={bodyId}
                onClick={() => setView(key)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none',
                  view === key ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <Icon className="size-3.5" /> {label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div id={bodyId} className={cn('px-4 transition-opacity', busy && 'opacity-60')}>
        {view === 'chart' ? chart : <div className="max-h-80 overflow-auto rounded-lg border">{table}</div>}
      </div>
    </Card>
  )
}
