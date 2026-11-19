import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Keeps list state (filters, sorting, page) in the URL so refresh, back/forward and shared links
 * all land on the same view.
 */
export function useUrlParams() {
  const [searchParams, setSearchParams] = useSearchParams()

  /** Merge changes into the URL. Any change other than paging returns to page 1. */
  const update = useCallback(
    (patch: Record<string, string | undefined>) => {
      // Build from the LIVE url, not a render-time snapshot: two quick changes (a debounced search firing
      // while a select changes, say) must each see the other's result instead of overwriting it.
      const next = new URLSearchParams(window.location.search)
      for (const [key, value] of Object.entries(patch)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      if (!('page' in patch)) next.delete('page')
      setSearchParams(next, { replace: true })
    },
    [setSearchParams],
  )

  const clear = useCallback(() => setSearchParams(new URLSearchParams(), { replace: true }), [setSearchParams])

  return { searchParams, update, clear }
}
