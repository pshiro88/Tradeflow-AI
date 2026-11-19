import { History, Info, Loader2, Send, ShieldCheck, WifiOff } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'

import { AiLabel } from '@/components/common/AiLabel'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { getErrorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ChatResponse } from '@/types/ai'

import { useAIStatus, useChat, useHistory, useSuggestions } from './hooks'

const MAX_LENGTH = 500

type Message =
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'assistant'; response: ChatResponse }
  | { id: number; role: 'error'; text: string }

export default function CopilotPage() {
  const chat = useChat()
  const aiStatus = useAIStatus()
  const suggestions = useSuggestions()
  const history = useHistory()
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const nextId = useRef(1)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, chat.isPending])

  const ask = (question: string) => {
    const text = question.trim()
    if (!text || chat.isPending) return
    setMessages((m) => [...m, { id: nextId.current++, role: 'user', text }])
    setDraft('')
    chat.mutate(text, {
      onSuccess: (response) => setMessages((m) => [...m, { id: nextId.current++, role: 'assistant', response }]),
      onError: (error) => setMessages((m) => [...m, { id: nextId.current++, role: 'error', text: getErrorMessage(error) }]),
    })
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    ask(draft)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      ask(draft)
    }
  }

  return (
    <>
      <PageHeader title="AI Copilot" description="Ask questions about your invoices, payments, reconciliation and documents." />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="flex min-h-[32rem] flex-col gap-0 py-0 lg:col-span-2">
          {aiStatus.data?.available === false && (
            <p className="flex items-start gap-2 border-b bg-warning/10 px-4 py-2.5 text-sm text-warning">
              <WifiOff className="mt-0.5 size-4 shrink-0" />
              The local AI model is offline. You will still get answers from your data, worded by fixed rules.
            </p>
          )}

          <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite" aria-label="Conversation">
            {messages.length === 0 && <Welcome suggestions={suggestions.data ?? []} onPick={ask} />}
            {messages.map((m) =>
              m.role === 'user' ? (
                <UserBubble key={m.id} text={m.text} />
              ) : m.role === 'error' ? (
                <p key={m.id} role="alert" className="max-w-[85%] rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {m.text}
                </p>
              ) : (
                <AssistantMessage key={m.id} response={m.response} onPick={ask} />
              ),
            )}
            {chat.isPending && (
              <div role="status" className="flex max-w-[85%] items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin text-primary" />
                Looking at your data{aiStatus.data?.available === false ? '' : ' and writing a reply. This can take a few seconds'}…
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form onSubmit={onSubmit} className="border-t p-3">
            <div className="flex items-end gap-2">
              <Textarea
                aria-label="Your question"
                placeholder="Ask about overdue invoices, payments, discrepancies…"
                rows={2}
                maxLength={MAX_LENGTH}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                className="min-h-0 resize-none"
              />
              <Button type="submit" disabled={chat.isPending || draft.trim() === ''}>
                <Send className="size-4" /> Send
              </Button>
            </div>
            <p className="mt-1.5 flex justify-between text-xs text-muted-foreground">
              <span>Enter to send, Shift+Enter for a new line</span>
              <span>
                {draft.length}/{MAX_LENGTH}
              </span>
            </p>
          </form>
        </Card>

        <div className="space-y-6">
          {messages.length > 0 && (
            <Card className="gap-3 p-4">
              <h2 className="font-medium text-navy">Suggested questions</h2>
              <SuggestionChips suggestions={suggestions.data ?? []} onPick={ask} disabled={chat.isPending} />
            </Card>
          )}

          <Card className="gap-0 py-0">
            <h2 className="flex items-center gap-2 border-b px-4 py-3 font-medium text-navy">
              <History className="size-4" /> Your recent questions
            </h2>
            {history.data && history.data.length > 0 ? (
              <ul className="divide-y">
                {history.data.map((h) => (
                  <li key={h.id}>
                    <button
                      type="button"
                      onClick={() => ask(h.question)}
                      disabled={chat.isPending}
                      className="flex w-full flex-col gap-0.5 px-4 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none disabled:opacity-60"
                      title="Ask again with the latest data"
                    >
                      <span className="line-clamp-2 font-medium">{h.question}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatDateTime(h.created_at)} · {h.generated_by === 'AI' ? 'AI wording' : 'standard answer'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">Your questions will appear here. Only you can see them.</p>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

function Welcome({ suggestions, onPick }: { suggestions: string[]; onPick: (q: string) => void }) {
  return (
    <div className="space-y-4 py-4">
      <div className="flex items-start gap-3 rounded-lg border bg-muted/30 p-4 text-sm">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
        <div className="space-y-1">
          <p className="font-medium text-navy">Answers come from your own data</p>
          <p className="text-muted-foreground">
            The assistant looks up your records with fixed queries, and the AI only words the result. It never changes
            anything, never invents numbers, and every answer shows the records behind it.
          </p>
        </div>
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium text-navy">Try asking</p>
        <SuggestionChips suggestions={suggestions} onPick={onPick} />
      </div>
    </div>
  )
}

function SuggestionChips({ suggestions, onPick, disabled }: { suggestions: string[]; onPick: (q: string) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap gap-2">
      {suggestions.map((q) => (
        <button
          key={q}
          type="button"
          disabled={disabled}
          onClick={() => onPick(q)}
          className="rounded-full border bg-card px-3 py-1.5 text-left text-sm transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-60"
        >
          {q}
        </button>
      ))}
    </div>
  )
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm whitespace-pre-wrap text-primary-foreground">{text}</p>
    </div>
  )
}

function AssistantMessage({ response, onPick }: { response: ChatResponse; onPick: (q: string) => void }) {
  const unknownOrDenied = response.intent === 'UNKNOWN' || /isn't available for your role/.test(response.answer)
  return (
    <div className="max-w-[92%] space-y-3 rounded-2xl rounded-bl-sm border bg-card p-4 text-sm">
      <AiLabel generatedBy={response.generated_by} />
      <p className="whitespace-pre-line">{response.answer}</p>

      {response.ai_note && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" /> {response.ai_note}
        </p>
      )}

      {response.generated_by === 'AI' && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground">Show the standard answer</summary>
          <p className="mt-1.5 rounded-md bg-muted/50 p-2 whitespace-pre-line">{response.standard_answer}</p>
        </details>
      )}

      {response.table && response.table.rows.length > 0 && (
        <div className="overflow-hidden rounded-lg border">
          <p className="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground">{response.table.title}</p>
          <div className="max-h-64 overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  {response.table.columns.map((c) => (
                    <TableHead key={c.key} className={cn('h-8 text-xs', c.align === 'right' && 'text-right')}>
                      {c.label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {response.table.rows.map((row, i) => (
                  <TableRow key={i}>
                    {response.table!.columns.map((c) => (
                      <TableCell key={c.key} className={cn('py-1.5 text-xs whitespace-nowrap', c.align === 'right' && 'text-right tabular-nums')}>
                        {row[c.key]}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {response.sources.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Sources:</span>
          {response.sources.slice(0, 8).map((s) => (
            <Link
              key={`${s.type}-${s.label}`}
              to={s.path}
              className="rounded-full border px-2 py-0.5 text-primary hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              {s.label}
            </Link>
          ))}
        </div>
      )}

      {unknownOrDenied && <SuggestionChips suggestions={response.suggestions} onPick={onPick} />}
    </div>
  )
}
