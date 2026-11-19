import { useQuery } from '@tanstack/react-query'
import { Activity, Database, FileCheck2, FileText, Receipt } from 'lucide-react'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/common/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/features/auth/useAuth'
import { fetchHealth } from '@/services/system'

const SHORTCUTS = [
  { to: '/invoices', icon: Receipt, title: 'Invoices', text: 'Look up an invoice and its payment status.' },
  { to: '/documents', icon: FileText, title: 'Documents', text: 'Upload trade documents and review extracted data.' },
  { to: '/compliance', icon: FileCheck2, title: 'Compliance', text: 'Check document completeness per invoice.' },
]

/**
 * Landing page for Operations. The financial dashboard exposes payment data, which Operations does not
 * have access to, so this role gets shortcuts to its own work instead.
 */
export default function OperationsHome() {
  const { user } = useAuth()
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth, retry: false })

  return (
    <>
      <PageHeader
        title="Overview"
        description={`Welcome back, ${user?.full_name.split(' ')[0] ?? ''}. Here is where your work is.`}
      />
      <div className="mb-6 grid gap-4 md:grid-cols-3">
        {SHORTCUTS.map(({ to, icon: Icon, title, text }) => (
          <Link key={to} to={to} className="rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">
            <Card className="h-full transition-colors hover:border-primary/40">
              <CardContent className="space-y-2">
                <Icon className="size-5 text-primary" />
                <p className="font-medium text-navy">{title}</p>
                <p className="text-sm text-muted-foreground">{text}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="size-4" /> System status
          </CardTitle>
          <CardDescription>Live check against the backend</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="flex items-center justify-between">
            <span>API</span>
            {health.isPending ? (
              <Badge variant="secondary">Checking…</Badge>
            ) : health.isError ? (
              <Badge variant="destructive">Unreachable</Badge>
            ) : (
              <Badge className="bg-success text-white">Online</Badge>
            )}
          </div>
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Database className="size-4" /> Database
            </span>
            {health.data ? <Badge className="bg-success text-white">{health.data.database}</Badge> : <Badge variant="secondary">—</Badge>}
          </div>
        </CardContent>
      </Card>
    </>
  )
}
