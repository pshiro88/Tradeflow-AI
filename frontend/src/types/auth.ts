export type UserRole = 'ADMIN' | 'FINANCE' | 'OPERATIONS'

export interface User {
  id: string
  full_name: string
  email: string
  role: UserRole
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface LoginPayload {
  email: string
  password: string
}
