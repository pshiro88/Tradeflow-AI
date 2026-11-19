import { PageHeader } from '@/components/common/PageHeader'
import { useUrlParams } from '@/hooks/useUrlParams'

import { OutstandingInvoicesCard, RecentTransactionsCard } from './ActivityCards'
import { DashboardFilterBar, parseDashboardFilters } from './DashboardFilterBar'
import { CurrencyDistributionCard, StatusDistributionCard } from './DistributionCharts'
import { KpiTiles } from './KpiTiles'
import { TrendChart } from './TrendChart'

/** Finance / Admin dashboard. Every number comes from database aggregates via /dashboard/*. */
export default function DashboardPage() {
  const { searchParams } = useUrlParams()
  const filters = parseDashboardFilters(searchParams)

  return (
    <>
      <PageHeader title="Overview" description="Where your export invoices and incoming payments stand." />
      <DashboardFilterBar filters={filters} />

      <div className="space-y-6">
        <KpiTiles filters={filters} />
        <TrendChart filters={filters} />
        <div className="grid gap-6 lg:grid-cols-2">
          <StatusDistributionCard filters={filters} />
          <CurrencyDistributionCard filters={filters} />
        </div>
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <RecentTransactionsCard filters={filters} />
          </div>
          <OutstandingInvoicesCard filters={filters} />
        </div>
      </div>
    </>
  )
}
