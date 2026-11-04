/**
 * API client for communicating with the Onigiri backend.
 *
 * Base URL is read from the VITE_API_BASE_URL environment variable.
 * Falls back to http://localhost:8000/api for local development.
 */

import type { MangaItem } from '../types/manga'

const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

// ── Response types ──────────────────────────────────────────

export interface HealthResponse {
  status: string
  service: string
  version: string
  timestamp: string
}

export interface SearchMangaParams {
  q: string
  page?: number
  limit?: number
}

// ── Error handling ──────────────────────────────────────────

export class ApiError extends Error {
  statusCode: number

  constructor(statusCode: number, message: string) {
    super(message)
    this.statusCode = statusCode
    this.name = 'ApiError'
  }
}

export class NetworkError extends Error {
  constructor(message: string = 'Сервер недоступен') {
    super(message)
    this.name = 'NetworkError'
  }
}

// ── Core fetch wrapper ──────────────────────────────────────

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${endpoint}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new NetworkError()
  }

  if (!response.ok) {
    throw new ApiError(response.status, `API error: ${response.status}`)
  }

  return response.json() as Promise<T>
}

// ── API methods ─────────────────────────────────────────────

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

export async function fetchMangaSearch(params: SearchMangaParams): Promise<MangaItem[]> {
  const cleanQuery = params.q.trim()
  if (!cleanQuery) {
    return []
  }

  const queryParams = new URLSearchParams({
    q: cleanQuery,
    page: String(params.page ?? 1),
    limit: String(params.limit ?? 20),
  })

  return request<MangaItem[]>(`/manga/search?${queryParams.toString()}`)
}
