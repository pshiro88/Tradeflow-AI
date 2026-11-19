import { PageHeader } from '@/components/common/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/features/auth/useAuth'
import { usePersistentState } from '@/hooks/usePersistentState'
import { NAV_ITEMS, canAccess } from '@/routes/navigation'

// Timestamps are stored in UTC by the backend and displayed in the timezone chosen here.
const TIMEZONES = [
  { value: 'Asia/Kolkata', label: 'India (IST)' },
  { value: 'Asia/Dubai', label: 'Dubai (GST)' },
  { value: 'Europe/London', label: 'London' },
  { value: 'Europe/Berlin', label: 'Central Europe' },
  { value: 'America/New_York', label: 'New York' },
  { value: 'UTC', label: 'UTC' },
]

export const TIMEZONE_STORAGE_KEY = 'tradeflow.timezone'

export default function SettingsPage() {
  const { user } = useAuth()
  const [timezone, setTimezone] = usePersistentState<string>(TIMEZONE_STORAGE_KEY, 'Asia/Kolkata')

  if (!user) return null
  const accessible = NAV_ITEMS.filter((route) => canAccess(route, user.role))

  return (
    <>
      <PageHeader title="Settings" description="Your profile and display preferences." />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription>Account details are managed by an administrator.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Name</span>
              <span className="font-medium">{user.full_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Email</span>
              <span className="font-medium">{user.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Role</span>
              <Badge variant="secondary">{user.role}</Badge>
            </div>
            <div className="space-y-2 border-t pt-3">
              <span className="text-muted-foreground">Modules you can access</span>
              <div className="flex flex-wrap gap-2">
                {accessible.map((route) => (
                  <Badge key={route.path} variant="outline">
                    {route.label}
                  </Badge>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Display</CardTitle>
            <CardDescription>Choose the timezone used to show dates and times.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Label htmlFor="timezone">Timezone</Label>
            <select
              id="timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="h-9 w-full rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {TIMEZONES.map((tz) => (
                <option key={tz.value} value={tz.value}>
                  {tz.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">Stored on this device only.</p>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
