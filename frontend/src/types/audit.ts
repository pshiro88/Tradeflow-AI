export interface AuditLogItem {
  id: string
  created_at: string
  user_id: string | null
  user_name: string | null
  action: string
  entity_type: string
  entity_id: string | null
  old_values: Record<string, unknown> | null
  new_values: Record<string, unknown> | null
}

export interface AIAuditItem {
  id: string
  created_at: string
  user_id: string | null
  user_name: string | null
  operation_type: string
  model_name: string
  request_summary: string | null
  response_summary: string | null
  status: string
  duration_ms: number | null
  details: Record<string, unknown> | null
}

export interface AuditOptions {
  users: { id: string; name: string }[]
  actions: string[]
  entity_types: string[]
  ai_operations: string[]
  ai_statuses: string[]
}

export interface AuditListParams {
  page: number
  page_size: number
  user_id?: string
  action?: string
  entity_type?: string
  search?: string
  date_from?: string
  date_to?: string
}

export interface AIAuditListParams {
  page: number
  page_size: number
  user_id?: string
  operation?: string
  status?: string
  search?: string
  date_from?: string
  date_to?: string
}
