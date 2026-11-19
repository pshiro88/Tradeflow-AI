const METHOD_LABELS: Record<string, string> = {
  EXACT_REFERENCE: 'Exact reference',
  NAME_AND_AMOUNT: 'Buyer name + amount',
  DUPLICATE_SIGNATURE: 'Duplicate check',
  MANUAL_APPROVAL: 'Manual approval',
}

export function methodLabel(method: string | null): string {
  return method ? (METHOD_LABELS[method] ?? method) : 'No match'
}

/** Confidence is an estimate for reviewers, not a probability. */
export function confidenceLabel(confidence: string | null): string {
  return confidence === null ? '—' : `${Number(confidence).toFixed(0)}%`
}
