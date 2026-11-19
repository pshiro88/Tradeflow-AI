const TOKEN_KEY = 'tradeflow.access_token'

// localStorage keeps the demo simple (survives refresh). Trade-off: readable by injected scripts;
// a production build would prefer an httpOnly cookie.
export const authStorage = {
  getToken(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  setToken(token: string): void {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* storage unavailable: session lasts until reload */
    }
  },
  clear(): void {
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* ignore */
    }
  },
}

// Fired when the API rejects our token, so the auth provider can drop the session.
export const UNAUTHORIZED_EVENT = 'tradeflow:unauthorized'
