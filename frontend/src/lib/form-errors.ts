import axios from 'axios'
import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'

import { getErrorMessage } from '@/lib/api'

/**
 * Show a FastAPI error on a form. Pydantic validation errors (422 with a list) are mapped onto the
 * matching fields; any other error becomes a form-level message. Returns true if a field error was set.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  options: { knownFields: readonly string[]; conflictField?: Path<T> },
): void {
  if (axios.isAxiosError(error) && error.response) {
    const { status, data } = error.response
    const detail: unknown = data?.detail

    if (status === 422 && Array.isArray(detail)) {
      let mapped = false
      for (const item of detail as { loc?: (string | number)[]; msg?: string }[]) {
        const field = item.loc?.[item.loc.length - 1]
        if (typeof field === 'string' && options.knownFields.includes(field)) {
          // Pydantic prefixes messages with "Value error, "; strip it for display.
          setError(field as Path<T>, { message: (item.msg ?? 'Invalid value').replace(/^Value error, /, '') })
          mapped = true
        }
      }
      if (mapped) return
    }

    if (status === 409 && options.conflictField && typeof detail === 'string' && /already exists/i.test(detail)) {
      setError(options.conflictField, { message: detail })
      return
    }
  }
  setError('root', { message: getErrorMessage(error) })
}
