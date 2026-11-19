import { Construction } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'

import { PageHeader } from './PageHeader'

interface PlaceholderPageProps {
  title: string
  description: string
  /** Which build step delivers this module. */
  step: string
}

/** Temporary page for modules that are not built yet. */
export function PlaceholderPage({ title, description, step }: PlaceholderPageProps) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <Construction className="size-8 text-muted-foreground" />
          <p className="font-medium text-navy">This module is under construction</p>
          <p className="max-w-md text-sm text-muted-foreground">Planned for {step} of the implementation plan.</p>
        </CardContent>
      </Card>
    </>
  )
}
