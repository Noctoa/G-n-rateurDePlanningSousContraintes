// Client HTTP typé vers le backend FastAPI.
// En dev, Vite proxifie /api vers http://localhost:8000 (voir vite.config.ts).

export interface Health {
  status: string
  version: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const BASE_URL: string = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw new ApiError(response.status, await response.text())
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>('/health'),
}
