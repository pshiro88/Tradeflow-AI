import {
  BrainCircuit,
  FileCheck2,
  FileText,
  LayoutDashboard,
  Receipt,
  Scale,
  ScrollText,
  Settings,
  Wallet,
  type LucideIcon,
} from 'lucide-react'

import type { UserRole } from '@/types/auth'

export interface NavItem {
  path: string
  /** Short label for the sidebar and breadcrumbs. */
  label: string
  icon: LucideIcon
  /** Roles allowed to see the page. ADMIN is always allowed. Omit for all roles; [] means admin only. */
  roles?: UserRole[]
}

/**
 * Single source of truth for navigation, role visibility and breadcrumbs.
 * Visibility here is a UX convenience; the backend enforces the real permissions.
 */
export const NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Overview', icon: LayoutDashboard },
  { path: '/invoices', label: 'Invoices', icon: Receipt },
  { path: '/payments', label: 'Payments', icon: Wallet, roles: ['FINANCE'] },
  { path: '/reconciliation', label: 'Reconciliation', icon: Scale, roles: ['FINANCE'] },
  { path: '/documents', label: 'Documents', icon: FileText, roles: ['OPERATIONS'] },
  { path: '/compliance', label: 'Compliance', icon: FileCheck2, roles: ['OPERATIONS'] },
  { path: '/copilot', label: 'AI Copilot', icon: BrainCircuit },
  { path: '/audit-logs', label: 'Audit Logs', icon: ScrollText, roles: [] },
  { path: '/settings', label: 'Settings', icon: Settings },
]

export function canAccess(item: NavItem, role: UserRole): boolean {
  return role === 'ADMIN' || !item.roles || item.roles.includes(role)
}
