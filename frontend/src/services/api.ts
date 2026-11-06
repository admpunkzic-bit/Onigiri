/**
 * API client for communicating with the Onigiri backend.
 *
 * Base URL is read from the VITE_API_BASE_URL environment variable.
 * Falls back to http://localhost:8000/api for local development.
 */

import type {
  ChapterItem,
  ChapterReaderDetail,
  MangaDetail,
  MangaItem,
  ReadingProgress,
} from '../types/manga'

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

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string>),
  }

  // Forward Telegram WebApp initData for cryptographically verified auth
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (tgInitData && tgInitData.trim().length > 0) {
    headers['Authorization'] = `Telegram ${tgInitData.trim()}`
  }

  try {
    response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers,
    })
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
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

export function fetchMangaDetail(idOrSlug: string): Promise<MangaDetail> {
  return request<MangaDetail>(`/manga/${encodeURIComponent(idOrSlug.trim())}`)
}

export function fetchMangaChapters(
  idOrSlug: string,
  order: 'asc' | 'desc' = 'asc'
): Promise<ChapterItem[]> {
  const queryParams = new URLSearchParams({ order })
  return request<ChapterItem[]>(
    `/manga/${encodeURIComponent(idOrSlug.trim())}/chapters?${queryParams.toString()}`
  )
}

export function syncMangaChapters(
  idOrSlug: string
): Promise<{ status: string; chapters_count: number }> {
  return request<{ status: string; chapters_count: number }>(
    `/manga/${encodeURIComponent(idOrSlug.trim())}/sync`,
    { method: 'POST' }
  )
}

export async function fetchChapterPages(
  idOrSlug: string,
  chapterId: number,
  signal?: AbortSignal
): Promise<ChapterReaderDetail> {
  const data = await request<ChapterReaderDetail>(
    `/manga/${encodeURIComponent(idOrSlug.trim())}/chapters/${chapterId}/pages`,
    { signal }
  )
  const baseUrl = (API_BASE_URL || 'http://localhost:8000/api').replace(/\/api\/?$/, '')
  return {
    ...data,
    pages: data.pages.map((p) => ({
      ...p,
      image_url: p.image_url.startsWith('http')
        ? p.image_url
        : `${baseUrl}${p.image_url.startsWith('/') ? '' : '/'}${p.image_url}`,
    })),
  }
}

export async function fetchReadingProgress(
  idOrSlug: string,
  signal?: AbortSignal
): Promise<ReadingProgress | null> {
  // If not in Telegram (Guest mode in browser), fetch from localStorage
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    try {
      const raw = localStorage.getItem(`onigiri_guest_progress_${idOrSlug.trim()}`)
      if (raw) return JSON.parse(raw) as ReadingProgress
    } catch {
      // Ignore localStorage errors
    }
    return null
  }

  try {
    return await request<ReadingProgress | null>(
      `/manga/${encodeURIComponent(idOrSlug.trim())}/progress`,
      { signal }
    )
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    return null
  }
}

export async function saveReadingProgress(
  idOrSlug: string,
  update: {
    chapter_id: number
    chapter_number?: number | null
    chapter_title?: string | null
    page_number: number
    total_pages?: number | null
  }
): Promise<ReadingProgress | null> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined

  // If not in Telegram (Guest mode in browser), save to localStorage only
  if (!tgInitData || tgInitData.trim().length === 0) {
    const localRecord: ReadingProgress = {
      manga_id: 0,
      chapter_id: update.chapter_id,
      chapter_number: update.chapter_number ?? null,
      chapter_title: update.chapter_title ?? null,
      page_number: update.page_number,
      total_pages: update.total_pages,
      updated_at: new Date().toISOString(),
    }
    try {
      localStorage.setItem(`onigiri_guest_progress_${idOrSlug.trim()}`, JSON.stringify(localRecord))
    } catch {
      // Ignore
    }
    return localRecord
  }

  try {
    return await request<ReadingProgress>(
      `/manga/${encodeURIComponent(idOrSlug.trim())}/progress`,
      {
        method: 'POST',
        body: JSON.stringify({
          chapter_id: update.chapter_id,
          page_number: update.page_number,
          total_pages: update.total_pages,
        }),
      }
    )
  } catch (err) {
    console.warn('Failed to save reading progress to backend:', err)
    return null
  }
}

export function getPageImageUrl(
  chapterId: number,
  pageNumber: number,
  dataSaver: boolean = false
): string {
  const query = dataSaver ? '?data_saver=true' : ''
  return `${API_BASE_URL}/manga/chapters/${chapterId}/pages/${pageNumber}${query}`
}
