import { api } from '@/lib/api'

export interface HealthResponse {
  status: string
  database: string
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health')
  return data
}
