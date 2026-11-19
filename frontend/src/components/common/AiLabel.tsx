import { Sparkles, FileText } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * Makes it obvious who wrote a piece of text (BRD: "Clear AI-generated response labels").
 * AI = worded by the local model from retrieved data; RULES = fixed text produced by the application.
 */
export function AiLabel({ generatedBy, className }: { generatedBy: 'AI' | 'RULES'; className?: string }) {
  const ai = generatedBy === 'AI'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        ai ? 'border-primary/25 bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
        className,
      )}
      title={
        ai
          ? 'Worded by the local AI model from your data. Check the table and records below it.'
          : 'Standard wording produced by fixed rules, not by the AI model.'
      }
    >
      {ai ? <Sparkles className="size-3" /> : <FileText className="size-3" />}
      {ai ? 'AI-generated wording' : 'Standard answer'}
    </span>
  )
}
