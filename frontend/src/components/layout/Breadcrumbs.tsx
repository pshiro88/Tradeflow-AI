import { ChevronRight } from 'lucide-react'
import { Fragment } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { NAV_ITEMS } from '@/routes/navigation'

interface Crumb {
  label: string
  to: string
}

function buildCrumbs(pathname: string): Crumb[] {
  const segments = pathname.split('/').filter(Boolean)
  if (segments.length === 0) return [{ label: 'Overview', to: '/' }]

  const base = NAV_ITEMS.find((r) => r.path === `/${segments[0]}`)
  const crumbs: Crumb[] = [{ label: 'Overview', to: '/' }]
  crumbs.push({ label: base?.label ?? segments[0], to: `/${segments[0]}` })
  // Deeper segments (e.g. /invoices/:id) are detail pages.
  if (segments.length > 1) crumbs.push({ label: 'Details', to: pathname })
  return crumbs
}

export function Breadcrumbs() {
  const { pathname } = useLocation()
  const crumbs = buildCrumbs(pathname)

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-muted-foreground">
      {crumbs.map((crumb, index) => {
        const isLast = index === crumbs.length - 1
        return (
          <Fragment key={crumb.to}>
            {index > 0 && <ChevronRight className="size-3.5" />}
            {isLast ? (
              <span aria-current="page" className="font-medium text-foreground">
                {crumb.label}
              </span>
            ) : (
              <Link to={crumb.to} className="hover:text-foreground">
                {crumb.label}
              </Link>
            )}
          </Fragment>
        )
      })}
    </nav>
  )
}
