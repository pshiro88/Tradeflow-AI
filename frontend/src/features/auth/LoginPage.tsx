import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2, ShieldCheck } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getErrorMessage } from '@/lib/api'
import { loginSchema, type LoginFormValues } from '@/schemas/auth'

import { useAuth } from './useAuth'

// Seeded demo accounts (synthetic data only). Mirrors backend/app/db/seed.py.
const DEMO_PASSWORD = 'Demo@12345'
const DEMO_ACCOUNTS = [
  { label: 'Admin', email: 'admin@example.com' },
  { label: 'Finance', email: 'finance@example.com' },
  { label: 'Operations', email: 'operations@example.com' },
]

export default function LoginPage() {
  const { user, status, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const redirectTo = (location.state as { from?: string } | null)?.from ?? '/'

  const {
    register,
    handleSubmit,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: '', password: '' } })

  if (status === 'authenticated' && user) return <Navigate to={redirectTo} replace />

  const onSubmit = handleSubmit(async (values) => {
    try {
      await login(values)
      navigate(redirectTo, { replace: true })
    } catch (error) {
      setError('root', { message: getErrorMessage(error, 'Unable to sign in. Please try again.') })
    }
  })

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="space-y-1 text-center">
          <div className="mx-auto mb-3 flex size-11 items-center justify-center rounded-xl bg-navy text-white">
            <ShieldCheck className="size-6" />
          </div>
          <h1 className="text-2xl font-semibold text-navy">TradeFlow AI</h1>
          <p className="text-sm text-muted-foreground">Sign in to your trade operations workspace</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Use your work email and password.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} noValidate className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  aria-invalid={!!errors.email}
                  {...register('email')}
                />
                {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  aria-invalid={!!errors.password}
                  {...register('password')}
                />
                {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
              </div>

              {errors.root && (
                <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {errors.root.message}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="size-4 animate-spin" />}
                Sign in
              </Button>
            </form>
          </CardContent>
        </Card>

        <div className="rounded-lg border border-dashed bg-card p-4 text-sm">
          <p className="mb-2 font-medium text-navy">Demo accounts</p>
          <p className="mb-3 text-muted-foreground">
            Synthetic data only. Click to fill the form (password: <code>{DEMO_PASSWORD}</code>).
          </p>
          <div className="flex flex-wrap gap-2">
            {DEMO_ACCOUNTS.map((account) => (
              <Button
                key={account.email}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setValue('email', account.email, { shouldValidate: true })
                  setValue('password', DEMO_PASSWORD, { shouldValidate: true })
                }}
              >
                {account.label}
              </Button>
            ))}
          </div>
        </div>
      </div>
    </main>
  )
}
