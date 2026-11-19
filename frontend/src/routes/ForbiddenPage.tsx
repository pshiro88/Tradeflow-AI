import { ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'

export default function ForbiddenPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <ShieldAlert className="size-10 text-warning" />
      <h1 className="text-2xl font-semibold text-navy">Access denied</h1>
      <p className="max-w-sm text-muted-foreground">Your role does not have permission to view this page.</p>
      <Button nativeButton={false} render={<Link to="/" />}>
        Back to overview
      </Button>
    </main>
  )
}
