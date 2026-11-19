import { Bot, FileSearch, ScrollText, X } from 'lucide-react'
import { useState } from 'react'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { PageHeader } from '@/components/common/PageHeader'
import { Pagination } from '@/components/common/Pagination'
import { StatusBadge, type StatusTone } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useUrlParams } from '@/hooks/useUrlParams'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { AIAuditItem, AuditLogItem } from '@/types/audit'

import { useActivityLogs, useAIRequestLogs, useAuditOptions } from './hooks'

const PAGE_SIZE = 20

const humanize = (value: string) => {
  const text = value.replaceAll('_', ' ').toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

const AI_TONE: Record<string, StatusTone> = { SUCCESS: 'success', NO_DATA: 'neutral', UNKNOWN: 'neutral', DENIED: 'warning', FAILED: 'danger' }
const aiTone = (status: string): StatusTone => AI_TONE[status] ?? (status.startsWith('FALLBACK') || status.startsWith('REJECTED') || status === 'UNAVAILABLE' ? 'warning' : 'neutral')

export default function AuditLogsPage() {
  const { searchParams, update, clear } = useUrlParams()
  const tab = searchParams.get('tab') === 'ai' ? 'ai' : 'activity'
  const page = Math.max(1, Number(searchParams.get('page')) || 1)
  const [searchInput, setSearchInput] = useState(searchParams.get('q') ?? '')
  const search = useDebouncedValue(searchInput).trim() || undefined
  const options = useAuditOptions()

  const shared = {
    page,
    page_size: PAGE_SIZE,
    user_id: searchParams.get('user') || undefined,
    search,
    date_from: searchParams.get('from') || undefined,
    date_to: searchParams.get('to') || undefined,
  }
  const activity = useActivityLogs({ ...shared, action: searchParams.get('action') || undefined, entity_type: searchParams.get('entity') || undefined })
  const ai = useAIRequestLogs({ ...shared, operation: searchParams.get('op') || undefined, status: searchParams.get('status') || undefined }, tab === 'ai')
  const current = tab === 'ai' ? ai : activity

  const [activityRow, setActivityRow] = useState<AuditLogItem | null>(null)
  const [aiRow, setAiRow] = useState<AIAuditItem | null>(null)

  const hasFilters = ['user', 'action', 'entity', 'op', 'status', 'from', 'to', 'q'].some((k) => searchParams.get(k))
  const switchTab = (next: 'activity' | 'ai') => {
    setSearchInput('')
    clear()
    if (next === 'ai') update({ tab: 'ai' })
  }

  return (
    <>
      <PageHeader title="Audit Logs" description="A permanent record of important actions and AI requests. Entries can be read but never edited." />

      <div role="tablist" aria-label="Log type" className="mb-4 inline-flex rounded-lg border p-0.5">
        {(
          [
            ['activity', ScrollText, 'Activity'],
            ['ai', Bot, 'AI requests'],
          ] as const
        ).map(([key, Icon, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => switchTab(key)}
            className={cn('inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none', tab === key ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground')}
          >
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-end gap-3 border-b p-4">
          <Field label="Search" id="a-search">
            <Input id="a-search" className="w-52" placeholder={tab === 'ai' ? 'Search the question' : 'Search the action'} value={searchInput} onChange={(e) => { setSearchInput(e.target.value); update({ q: e.target.value.trim() || undefined }) }} />
          </Field>
          <Field label="User" id="a-user">
            <NativeSelect id="a-user" className="w-44" value={searchParams.get('user') ?? ''} onChange={(e) => update({ user: e.target.value || undefined })}>
              <option value="">Everyone</option>
              {options.data?.users.map((u) => (
                <option key={u.id} value={u.id}>{u.name}</option>
              ))}
            </NativeSelect>
          </Field>
          {tab === 'activity' ? (
            <>
              <Field label="Action" id="a-action">
                <NativeSelect id="a-action" className="w-56" value={searchParams.get('action') ?? ''} onChange={(e) => update({ action: e.target.value || undefined })}>
                  <option value="">All actions</option>
                  {options.data?.actions.map((a) => (
                    <option key={a} value={a}>{humanize(a)}</option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Record type" id="a-entity">
                <NativeSelect id="a-entity" className="w-44" value={searchParams.get('entity') ?? ''} onChange={(e) => update({ entity: e.target.value || undefined })}>
                  <option value="">All records</option>
                  {options.data?.entity_types.map((t) => (
                    <option key={t} value={t}>{humanize(t)}</option>
                  ))}
                </NativeSelect>
              </Field>
            </>
          ) : (
            <>
              <Field label="Operation" id="a-op">
                <NativeSelect id="a-op" className="w-48" value={searchParams.get('op') ?? ''} onChange={(e) => update({ op: e.target.value || undefined })}>
                  <option value="">All operations</option>
                  {options.data?.ai_operations.map((o) => (
                    <option key={o} value={o}>{humanize(o)}</option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Outcome" id="a-status">
                <NativeSelect id="a-status" className="w-52" value={searchParams.get('status') ?? ''} onChange={(e) => update({ status: e.target.value || undefined })}>
                  <option value="">All outcomes</option>
                  {options.data?.ai_statuses.map((s) => (
                    <option key={s} value={s}>{humanize(s)}</option>
                  ))}
                </NativeSelect>
              </Field>
            </>
          )}
          <Field label="From" id="a-from">
            <Input id="a-from" type="date" className="w-38" value={searchParams.get('from') ?? ''} onChange={(e) => update({ from: e.target.value || undefined })} />
          </Field>
          <Field label="To" id="a-to">
            <Input id="a-to" type="date" className="w-38" value={searchParams.get('to') ?? ''} onChange={(e) => update({ to: e.target.value || undefined })} />
          </Field>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={() => { setSearchInput(''); const t = tab; clear(); if (t === 'ai') update({ tab: 'ai' }) }}>
              <X className="size-4" /> Clear
            </Button>
          )}
        </div>

        {current.isError ? (
          <ErrorState error={current.error} onRetry={() => void current.refetch()} title="Could not load the logs" />
        ) : current.isPending ? (
          <div className="space-y-3 p-4" role="status" aria-label="Loading logs">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : current.data.total === 0 ? (
          <EmptyState icon={hasFilters ? FileSearch : ScrollText} title={hasFilters ? 'No entries match your filters' : 'Nothing recorded yet'} />
        ) : (
          <>
            <div className={cn('transition-opacity', current.isFetching && 'opacity-60')}>
              {tab === 'activity' ? (
                <ActivityTable rows={(activity.data?.items ?? []) as AuditLogItem[]} onOpen={setActivityRow} />
              ) : (
                <AITable rows={(ai.data?.items ?? []) as AIAuditItem[]} onOpen={setAiRow} />
              )}
            </div>
            <Pagination page={current.data.page} pages={current.data.pages} total={current.data.total} pageSize={current.data.page_size} onPageChange={(p) => update({ page: String(p) })} />
          </>
        )}
      </Card>

      <ActivitySheet row={activityRow} onClose={() => setActivityRow(null)} />
      <AISheet row={aiRow} onClose={() => setAiRow(null)} />
    </>
  )
}

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function ActivityTable({ rows, onOpen }: { rows: AuditLogItem[]; onOpen: (r: AuditLogItem) => void }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/40 hover:bg-muted/40">
          <TableHead>When</TableHead>
          <TableHead>User</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>Record</TableHead>
          <TableHead>Changes</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.id} tabIndex={0} className="cursor-pointer" onClick={() => onOpen(r)} onKeyDown={(e) => e.key === 'Enter' && onOpen(r)}>
            <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(r.created_at)}</TableCell>
            <TableCell>{r.user_name ?? <span className="text-muted-foreground">System</span>}</TableCell>
            <TableCell className="font-medium">{humanize(r.action)}</TableCell>
            <TableCell className="text-muted-foreground">
              {humanize(r.entity_type)}
              {r.entity_id && <span className="ml-1 font-mono text-xs">{r.entity_id.slice(0, 8)}</span>}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{summarise(r)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function summarise(r: AuditLogItem): string {
  const keys = Object.keys(r.new_values ?? r.old_values ?? {})
  if (keys.length === 0) return '—'
  return keys.slice(0, 3).map(humanize).join(', ') + (keys.length > 3 ? ` +${keys.length - 3}` : '')
}

function AITable({ rows, onOpen }: { rows: AIAuditItem[]; onOpen: (r: AIAuditItem) => void }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/40 hover:bg-muted/40">
          <TableHead>When</TableHead>
          <TableHead>User</TableHead>
          <TableHead>Operation</TableHead>
          <TableHead>Model</TableHead>
          <TableHead>Outcome</TableHead>
          <TableHead className="text-right">Time</TableHead>
          <TableHead>Request</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.id} tabIndex={0} className="cursor-pointer" onClick={() => onOpen(r)} onKeyDown={(e) => e.key === 'Enter' && onOpen(r)}>
            <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(r.created_at)}</TableCell>
            <TableCell>{r.user_name ?? '—'}</TableCell>
            <TableCell className="font-medium">{humanize(r.operation_type)}</TableCell>
            <TableCell className="text-muted-foreground">{r.model_name}</TableCell>
            <TableCell><StatusBadge label={humanize(r.status)} tone={aiTone(r.status)} /></TableCell>
            <TableCell className="text-right whitespace-nowrap tabular-nums">{r.duration_ms === null ? '—' : `${(r.duration_ms / 1000).toFixed(1)} s`}</TableCell>
            <TableCell className="max-w-xs truncate text-sm text-muted-foreground" title={r.request_summary ?? undefined}>{r.request_summary}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

const show = (value: unknown): string => (value === null || value === undefined ? '—' : typeof value === 'string' ? value : JSON.stringify(value))

function ActivitySheet({ row, onClose }: { row: AuditLogItem | null; onClose: () => void }) {
  const keys = row ? [...new Set([...Object.keys(row.old_values ?? {}), ...Object.keys(row.new_values ?? {})])] : []
  return (
    <Sheet open={!!row} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle>{row ? humanize(row.action) : 'Entry'}</SheetTitle>
          <SheetDescription>{row && `${formatDateTime(row.created_at)} · ${row.user_name ?? 'System'}`}</SheetDescription>
        </SheetHeader>
        {row && (
          <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
            <dl className="grid grid-cols-[8rem_1fr] gap-y-1.5">
              <dt className="text-muted-foreground">Record type</dt><dd>{humanize(row.entity_type)}</dd>
              <dt className="text-muted-foreground">Record id</dt><dd className="font-mono text-xs break-all">{row.entity_id ?? '—'}</dd>
              <dt className="text-muted-foreground">Entry id</dt><dd className="font-mono text-xs break-all">{row.id}</dd>
            </dl>
            {keys.length === 0 ? (
              <p className="text-muted-foreground">No values were recorded for this entry.</p>
            ) : (
              <div className="overflow-hidden rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40 hover:bg-muted/40"><TableHead>Field</TableHead><TableHead>Before</TableHead><TableHead>After</TableHead></TableRow>
                  </TableHeader>
                  <TableBody>
                    {keys.map((k) => {
                      const before = row.old_values?.[k]
                      const after = row.new_values?.[k]
                      const changed = show(before) !== show(after)
                      return (
                        <TableRow key={k} className={cn(changed && 'bg-warning/5')}>
                          <TableCell className="font-medium">{humanize(k)}</TableCell>
                          <TableCell className="break-words whitespace-normal text-muted-foreground">{show(before)}</TableCell>
                          <TableCell className={cn('break-words whitespace-normal', changed && 'font-medium')}>{show(after)}</TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

function AISheet({ row, onClose }: { row: AIAuditItem | null; onClose: () => void }) {
  return (
    <Sheet open={!!row} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle>{row ? humanize(row.operation_type) : 'AI request'}</SheetTitle>
          <SheetDescription>{row && `${formatDateTime(row.created_at)} · ${row.user_name ?? 'unknown user'} · ${row.model_name}`}</SheetDescription>
        </SheetHeader>
        {row && (
          <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
            <div className="flex items-center gap-2">
              <StatusBadge label={humanize(row.status)} tone={aiTone(row.status)} />
              <span className="text-muted-foreground">{row.duration_ms === null ? '' : `${(row.duration_ms / 1000).toFixed(1)} seconds`}</span>
            </div>
            <section><h3 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Request</h3><p className="rounded-md bg-muted/40 p-3 whitespace-pre-wrap">{row.request_summary ?? '—'}</p></section>
            <section><h3 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Response</h3><p className="rounded-md bg-muted/40 p-3 whitespace-pre-wrap">{row.response_summary ?? '—'}</p></section>
            {row.details && (
              <section><h3 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Details</h3><pre className="overflow-x-auto rounded-md bg-muted/40 p-3 text-xs">{JSON.stringify(row.details, null, 2)}</pre></section>
            )}
            <p className="text-xs text-muted-foreground">Only short summaries are kept. Full document text is never stored in the log.</p>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
