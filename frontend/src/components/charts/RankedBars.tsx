import type { ReactNode } from 'react'
import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { ChartTooltip } from './ChartTooltip'

export interface RankedBarDatum {
  label: string
  value: number
  /** Extra rows shown in the tooltip, e.g. money in the row's own currency. */
  details?: { label: string; value: ReactNode }[]
}

interface RankedBarsProps {
  data: RankedBarDatum[]
  /** What the bar length measures, e.g. "payments". Used in the tooltip and the accessible label. */
  measure: string
  ariaLabel: string
  labelWidth?: number
}

const ROW_HEIGHT = 40

/**
 * Part-to-whole as ranked horizontal bars: one series, one hue (categorical slot 1), largest first,
 * value printed at the bar tip. Bars are thin (<= 18px) with a 4px rounded data end and a square baseline.
 */
export function RankedBars({ data, measure, ariaLabel, labelWidth = 104 }: RankedBarsProps) {
  return (
    <div role="img" aria-label={ariaLabel} style={{ height: data.length * ROW_HEIGHT + 8 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart layout="vertical" data={data} margin={{ top: 0, right: 44, bottom: 0, left: 0 }} barCategoryGap={14}>
          <XAxis type="number" hide domain={[0, 'dataMax']} />
          <YAxis
            type="category"
            dataKey="label"
            width={labelWidth}
            tickLine={false}
            axisLine={{ stroke: 'var(--viz-axis)' }}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
          />
          <Tooltip
            cursor={{ fill: 'var(--muted)', opacity: 0.6 }}
            content={({ active, payload }) => {
              const datum = active ? (payload?.[0]?.payload as RankedBarDatum | undefined) : undefined
              if (!datum) return null
              return (
                <ChartTooltip
                  title={datum.label}
                  rows={[{ swatch: 'var(--viz-1)', label: measure, value: datum.value }, ...(datum.details ?? [])]}
                />
              )
            }}
          />
          <Bar dataKey="value" fill="var(--viz-1)" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false}>
            <LabelList dataKey="value" position="right" fill="var(--foreground)" fontSize={12} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
