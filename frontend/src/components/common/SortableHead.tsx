import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import type { ReactNode } from 'react'

import { TableHead } from '@/components/ui/table'
import { cn } from '@/lib/utils'

interface SortableHeadProps {
  /** Whether the table is currently sorted by this column. */
  active: boolean
  direction: 'asc' | 'desc'
  onSort: () => void
  align?: 'right'
  children: ReactNode
}

/** Clickable column header that exposes its sort state to assistive tech via aria-sort. */
export function SortableHead({ active, direction, onSort, align, children }: SortableHeadProps) {
  const Icon = !active ? ArrowUpDown : direction === 'asc' ? ArrowUp : ArrowDown
  return (
    <TableHead
      className={align === 'right' ? 'text-right' : undefined}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        onClick={onSort}
        className={cn(
          'inline-flex items-center gap-1 hover:text-foreground',
          active ? 'text-foreground' : 'text-muted-foreground',
        )}
      >
        {children}
        <Icon className="size-3.5" />
      </button>
    </TableHead>
  )
}
