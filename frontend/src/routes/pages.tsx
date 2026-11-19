import type { ReactNode } from 'react'

import OverviewPage from '@/features/dashboard/OverviewPage'
import AuditLogsPage from '@/features/audit/AuditLogsPage'
import CompliancePage from '@/features/compliance/CompliancePage'
import CopilotPage from '@/features/copilot/CopilotPage'
import DocumentsPage from '@/features/documents/DocumentsPage'
import InvoicesPage from '@/features/invoices/InvoicesPage'
import PaymentsPage from '@/features/payments/PaymentsPage'
import ReconciliationPage from '@/features/reconciliation/ReconciliationPage'
import SettingsPage from '@/features/settings/SettingsPage'

/** Page element for each path in NAV_ITEMS. Placeholders are replaced as modules are built. */
export const PAGE_ELEMENTS: Record<string, ReactNode> = {
  '/': <OverviewPage />,
  '/invoices': <InvoicesPage />,
  '/payments': <PaymentsPage />,
  '/reconciliation': <ReconciliationPage />,
  '/documents': <DocumentsPage />,
  '/compliance': <CompliancePage />,
  '/copilot': <CopilotPage />,
  '/audit-logs': <AuditLogsPage />,
  '/settings': <SettingsPage />,
}
