import { useAuth } from '@/features/auth/useAuth'

import DashboardPage from './DashboardPage'
import OperationsHome from './OperationsHome'

/** Admin and Finance get the financial dashboard; Operations gets its own landing page. */
export default function OverviewPage() {
  const { user } = useAuth()
  return user?.role === 'OPERATIONS' ? <OperationsHome /> : <DashboardPage />
}
