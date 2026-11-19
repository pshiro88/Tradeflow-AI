import type { ReactNode } from 'react'

interface TooltipRow {
  /** Colour of the mark this row describes (identity comes from the swatch, never from coloured text). */
  swatch?: string
  label: string
  value: ReactNode
}

interface ChartTooltipProps {
  title: string
  rows: TooltipRow[]
  footer?: ReactNode
}

/** Shared hover card. Text uses text tokens; only the small swatch carries the series colour. */
export function ChartTooltip({ title, rows, footer }: ChartTooltipProps) {
  return (
    <div className="min-w-44 rounded-lg border bg-card px-3 py-2 text-sm shadow-md">
      <p className="mb-1 font-medium text-foreground">{title}</p>
      <ul className="space-y-1">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-2 text-muted-foreground">
              {row.swatch && <span className="size-2.5 rounded-[3px]" style={{ background: row.swatch }} />}
              {row.label}
            </span>
            <span className="font-medium text-foreground tabular-nums">{row.value}</span>
          </li>
        ))}
      </ul>
      {footer && <div className="mt-1 border-t pt-1 text-xs text-muted-foreground">{footer}</div>}
    </div>
  )
}
