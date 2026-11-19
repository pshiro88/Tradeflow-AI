import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'
import type { UserRole } from '@/types/auth'

interface ProtectedRouteProps {
  /** If set, only these roles (plus ADMIN) may view the route. */
  roles?: UserRole[]
}

/**
 * UX-level route guard only. The backend enforces the real permissions on every endpoint;
 * hiding a page here never replaces that check.
 */
export function ProtectedRoute({ roles }: ProtectedRouteProps) {
  const { user, status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading your workspace…
      </div>
    )
  }

  if (status === 'unauthenticated' || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  if (roles && user.role !== 'ADMIN' && !roles.includes(user.role)) {
    return <Navigate to="/forbidden" replace />
  }

  return <Outlet />
}
