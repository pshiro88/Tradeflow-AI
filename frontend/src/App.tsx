import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/layout/AppShell'
import LoginPage from '@/features/auth/LoginPage'
import InvoiceDetailPage from '@/features/invoices/InvoiceDetailPage'
import ForbiddenPage from '@/routes/ForbiddenPage'
import { ProtectedRoute } from '@/routes/ProtectedRoute'
import { NAV_ITEMS } from '@/routes/navigation'
import { PAGE_ELEMENTS } from '@/routes/pages'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forbidden" element={<ForbiddenPage />} />

      {/* Everything below requires a signed-in user and renders inside the app shell. */}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          {NAV_ITEMS.map(({ path, roles }) => (
            // Role-restricted pages get an extra guard (UX only; the API enforces permissions).
            <Route key={path} element={roles ? <ProtectedRoute roles={roles} /> : undefined}>
              <Route path={path} element={PAGE_ELEMENTS[path]} />
            </Route>
          ))}
          <Route path="/invoices/:invoiceId" element={<InvoiceDetailPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
