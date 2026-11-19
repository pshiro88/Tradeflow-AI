import { ShieldCheck } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { canAccess, NAV_ITEMS } from '@/routes/navigation'
import type { UserRole } from '@/types/auth'

interface SidebarProps {
  collapsed: boolean
  role: UserRole
}

export function Sidebar({ collapsed, role }: SidebarProps) {
  const items = NAV_ITEMS.filter((route) => canAccess(route, role))

  return (
    <aside
      className={cn(
        'flex shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      <div className={cn('flex h-16 items-center gap-3 border-b border-sidebar-border px-4', collapsed && 'justify-center px-0')}>
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-white">
          <ShieldCheck className="size-5" />
        </div>
        {!collapsed && (
          <div className="leading-tight">
            <p className="text-sm font-semibold text-white">TradeFlow AI</p>
            <p className="text-xs text-sidebar-foreground/70">Trade operations</p>
          </div>
        )}
      </div>

      <nav aria-label="Main" className="flex-1 space-y-1 p-3">
        {items.map(({ path, label, icon: Icon }) => {
          const link = (
            <NavLink
              to={path}
              end={path === '/'}
              aria-label={label}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  'hover:bg-sidebar-accent hover:text-white',
                  isActive ? 'bg-sidebar-accent text-white shadow-[inset_3px_0_0_0_var(--sidebar-primary)]' : '',
                  collapsed && 'justify-center px-0',
                )
              }
            >
              <Icon className="size-[18px] shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          )

          if (!collapsed) return <div key={path}>{link}</div>
          return (
            <Tooltip key={path}>
              <TooltipTrigger render={<div />}>{link}</TooltipTrigger>
              <TooltipContent side="right">{label}</TooltipContent>
            </Tooltip>
          )
        })}
      </nav>

      {!collapsed && (
        <p className="border-t border-sidebar-border p-4 text-xs text-sidebar-foreground/60">
          Demo build · synthetic data only
        </p>
      )}
    </aside>
  )
}
