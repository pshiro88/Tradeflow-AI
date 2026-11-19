import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { authStorage, UNAUTHORIZED_EVENT } from '@/lib/auth-storage'
import * as authService from '@/services/auth'
import type { LoginPayload, User } from '@/types/auth'

import { AuthContext, type AuthContextValue, type AuthStatus } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<User | null>(null)
  // With no stored token there is nothing to verify, so we can start unauthenticated.
  const [status, setStatus] = useState<AuthStatus>(() => (authStorage.getToken() ? 'loading' : 'unauthenticated'))

  const clearSession = useCallback(() => {
    authStorage.clear()
    setUser(null)
    setStatus('unauthenticated')
    queryClient.clear()
  }, [queryClient])

  // Restore the session on first load by asking the backend who the token belongs to.
  useEffect(() => {
    if (!authStorage.getToken()) return
    let cancelled = false
    authService
      .fetchCurrentUser()
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setStatus('authenticated')
      })
      .catch(() => {
        if (!cancelled) clearSession()
      })
    return () => {
      cancelled = true
    }
  }, [clearSession])

  // The Axios interceptor fires this when any request comes back 401 (expired / revoked token).
  useEffect(() => {
    window.addEventListener(UNAUTHORIZED_EVENT, clearSession)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, clearSession)
  }, [clearSession])

  const login = useCallback(async (payload: LoginPayload) => {
    const result = await authService.login(payload)
    authStorage.setToken(result.access_token)
    setUser(result.user)
    setStatus('authenticated')
    return result.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await authService.logout()
    } catch {
      /* token may already be invalid; local logout still proceeds */
    }
    clearSession()
  }, [clearSession])

  const value = useMemo<AuthContextValue>(() => ({ user, status, login, logout }), [user, status, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
