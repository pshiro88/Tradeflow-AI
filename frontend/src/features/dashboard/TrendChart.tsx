import { format, parseISO } from 'date-fns'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { ChartCard } from '@/components/charts/ChartCard'
import { ChartTooltip } from '@/components/charts/ChartTooltip'
import { ErrorState } from '@/components/common/ErrorState'
import { Skeleton } from '@/components/ui/skeleton'
import { NativeSelect } from '@/components/ui/native-select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatCompact, formatMoney } from '@/lib/format'
import type { DashboardFilters, TrendPoint } from '@/types/dashboard'

import { usePaymentTrends } from './hooks'

const RANGES = [3, 6, 12, 24]

// Series are fixed by entity: invoiced is always slot 1, received is always slot 2.
const SERIES = [
  { key: 'invoiced', name: 'Invoiced', color: 'var(--viz-1)' },
  { key: 'received', name: 'Received', color: 'var(--viz-2)' },
] as const

interface Datum {
  month: string
  label: string
  invoiced: number
  received: number
  raw: TrendPoint
}

export function TrendChart({ filters }: { filters: DashboardFilters }) {
  const [months, setMonths] = useState(6)
  const [chosenCurrency, setChosenCurrency] = useState<string | undefined>()
  // The shared currency filter wins; otherwise the card's own selector; otherwise the server picks the main one.
  const effective = { ...filters, currency: filters.currency ?? chosenCurrency }
  const { data, isPending, isError, error, refetch, isFetching } = usePaymentTrends(effective, months)

  const hasRange = !!(filters.date_from || filters.date_to)
  const actions = (
    <>
      <NativeSelect
        aria-label="Trend currency"
        className="h-7 w-20 text-xs"
        value={data?.currency ?? ''}
        disabled={!!filters.currency || !data}
        title={filters.currency ? 'Set by the currency filter above' : 'Amounts in different currencies are never added together'}
        onChange={(e) => setChosenCurrency(e.target.value)}
      >
        {(data?.available_currencies.length ? data.available_currencies : [data?.currency ?? 'USD']).map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </NativeSelect>
      <NativeSelect
        aria-label="Months shown"
        className="h-7 w-32 text-xs"
        value={months}
        disabled={hasRange}
        title={hasRange ? 'The date filter above sets the range' : undefined}
        onChange={(e) => setMonths(Number(e.target.value))}
      >
        {RANGES.map((m) => (
          <option key={m} value={m}>
            Last {m} months
          </option>
        ))}
      </NativeSelect>
    </>
  )

  if (isError) {
    return (
      <ChartCard
        title="Invoiced vs received"
        chart={<ErrorState error={error} onRetry={() => void refetch()} title="Could not load the trend" />}
        table={null}
      />
    )
  }
  if (isPending) {
    return (
      <ChartCard
        title="Invoiced vs received"
        description="Monthly, in one currency"
        chart={<Skeleton className="h-64 w-full" role="status" aria-label="Loading trend" />}
        table={null}
      />
    )
  }

  const currency = data.currency
  const rows: Datum[] = data.points.map((p) => ({
    month: p.month,
    label: format(parseISO(`${p.month}-01`), 'MMM yy'),
    invoiced: Number(p.invoiced), // plotting only; exact amounts stay as strings in `raw`
    received: Number(p.received),
    raw: p,
  }))
  const hasData = rows.some((r) => r.invoiced > 0 || r.received > 0)

  return (
    <ChartCard
      title="Invoiced vs received"
      description={`Monthly totals in ${currency}. Bank duplicates are not counted as received.`}
      actions={actions}
      busy={isFetching}
      chart={
        <div>
          <ul className="mb-2 flex items-center gap-4 text-sm text-muted-foreground" aria-label="Legend">
            {SERIES.map((s) => (
              <li key={s.key} className="flex items-center gap-2">
                <span className="size-2.5 rounded-[3px]" style={{ background: s.color }} />
                {s.name}
              </li>
            ))}
          </ul>
          {hasData ? (
            <div
              role="img"
              aria-label={`Grouped column chart of monthly invoiced and received amounts in ${currency}. Use the Table view for exact values.`}
              className="h-64"
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="28%">
                  <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
                  <XAxis
                    dataKey="label"
                    tickLine={false}
                    axisLine={{ stroke: 'var(--viz-axis)' }}
                    tick={{ fill: 'var(--viz-muted)', fontSize: 12 }}
                    interval={rows.length > 12 ? 1 : 0}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    width={48}
                    tickFormatter={formatCompact}
                    tick={{ fill: 'var(--viz-muted)', fontSize: 12 }}
                  />
                  <Tooltip
                    cursor={{ fill: 'var(--muted)', opacity: 0.6 }}
                    content={({ active, payload }) => {
                      const datum = active ? (payload?.[0]?.payload as Datum | undefined) : undefined
                      if (!datum) return null
                      return (
                        <ChartTooltip
                          title={datum.label}
                          rows={SERIES.map((s) => ({
                            swatch: s.color,
                            label: s.name,
                            value: formatMoney(datum.raw[s.key], currency),
                          }))}
                        />
                      )
                    }}
                  />
                  {SERIES.map((s) => (
                    <Bar
                      key={s.key}
                      dataKey={s.key}
                      name={s.name}
                      fill={s.color}
                      radius={[4, 4, 0, 0]}
                      maxBarSize={24}
                      isAnimationActive={false}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="flex h-64 items-center justify-center text-sm text-muted-foreground">
              No {currency} invoices or payments in this period.
            </p>
          )}
        </div>
      }
      table={
        <Table>
          <caption className="sr-only">Monthly invoiced and received amounts in {currency}</caption>
          <TableHeader>
            <TableRow>
              <TableHead>Month</TableHead>
              <TableHead className="text-right">Invoiced</TableHead>
              <TableHead className="text-right">Received</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.month}>
                <TableCell>{r.label}</TableCell>
                <TableCell className="text-right tabular-nums">{formatMoney(r.raw.invoiced, currency)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatMoney(r.raw.received, currency)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    />
  )
}
