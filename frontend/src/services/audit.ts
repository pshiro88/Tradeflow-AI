import { api } from '@/lib/api'
import type { AIAuditItem, AIAuditListParams, AuditListParams, AuditLogItem, AuditOptions } from '@/types/audit'
import type { Page } from '@/types/common'

export async function listActivity(params: AuditListParams): Promise<Page<AuditLogItem>> {
  const { data } = await api.get<Page<AuditLogItem>>('/audit-logs', { params })
  return data
}

export async function listAIRequests(params: AIAuditListParams): Promise<Page<AIAuditItem>> {
  const { data } = await api.get<Page<AIAuditItem>>('/audit-logs/ai', { params })
  return data
}

export async function getAuditOptions(): Promise<AuditOptions> {
  const { data } = await api.get<AuditOptions>('/audit-logs/options')
  return data
}
