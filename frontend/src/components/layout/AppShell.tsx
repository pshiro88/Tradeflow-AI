import { Outlet } from 'react-router-dom'

import { TooltipProvider } from '@/components/ui/tooltip'
import { useAuth } from '@/features/auth/useAuth'
import { usePersistentState } from '@/hooks/usePersistentState'

import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppShell() {
  const { user } = useAuth()
  // Start collapsed on narrow (tablet) screens unless the user chose otherwise before.
  const [collapsed, setCollapsed] = usePersistentState<boolean>('tradeflow.sidebar_collapsed', () => window.innerWidth < 1024)

  if (!user) return null

  return (
    <TooltipProvider>
      <div className="flex h-screen overflow-hidden bg-background">
        <Sidebar collapsed={collapsed} role={user.role} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar collapsed={collapsed} onToggleSidebar={() => setCollapsed((c) => !c)} />
          <main className="flex-1 overflow-y-auto p-4 md:p-6">
            <div className="mx-auto max-w-7xl">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}
