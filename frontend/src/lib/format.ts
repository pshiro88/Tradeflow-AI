import { format, parseISO } from 'date-fns'

const moneyFormatters = new Map<string, Intl.NumberFormat>()

/**
 * Format a money string from the API ("12500.00") for display.
 * The backend sends money as strings so no precision is lost in transit; Intl formats the decimal
 * string directly. Nothing in the UI does arithmetic on money.
 */
export function formatMoney(amount: string, currency: string): string {
  let formatter = moneyFormatters.get(currency)
  if (!formatter) {
    formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency, currencyDisplay: 'code' })
    moneyFormatters.set(currency, formatter)
  }
  return formatter.format(amount as unknown as number)
}

/** Format an ISO calendar date ("2026-11-16") as "16 Nov 2026". */
export function formatDate(value: string): string {
  return format(parseISO(value), 'dd MMM yyyy')
}

/** Format a UTC timestamp from the API in the timezone chosen in Settings. */
export function formatDateTime(value: string): string {
  let timeZone = 'Asia/Kolkata'
  try {
    const stored = localStorage.getItem('tradeflow.timezone')
    if (stored) timeZone = JSON.parse(stored) as string
  } catch {
    /* fall back to the default timezone */
  }
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(new Date(value))
}

const compactFormatter = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

/** 12500 -> "12.5K". For chart axes only; exact amounts always use formatMoney. */
export function formatCompact(value: number): string {
  return compactFormatter.format(value)
}
