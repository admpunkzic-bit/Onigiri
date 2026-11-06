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
  q?: string
  genre?: string[]
  excluded_genre?: string[]
  type?: string
  status?: string
  author?: string
  release_year?: number
  sort_by?: string
  sort_order?: string
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

export function fetchGenres(): Promise<Array<{ id: number; name: string; slug: string }>> {
  return request<Array<{ id: number; name: string; slug: string }>>('/manga/genres')
}

export async function fetchMangaSearch(
  params: SearchMangaParams,
  signal?: AbortSignal
): Promise<MangaItem[]> {
  const queryParams = new URLSearchParams()

  if (params.q?.trim()) {
    queryParams.set('q', params.q.trim())
  }
  if (params.genre && params.genre.length > 0) {
    for (const g of params.genre) {
      if (g.trim()) queryParams.append('genre', g.trim())
    }
  }
  if (params.excluded_genre && params.excluded_genre.length > 0) {
    for (const eg of params.excluded_genre) {
      if (eg.trim()) queryParams.append('excluded_genre', eg.trim())
    }
  }
  if (params.type?.trim()) {
    queryParams.set('type', params.type.trim())
  }
  if (params.status?.trim()) {
    queryParams.set('status', params.status.trim())
  }
  if (params.author?.trim()) {
    queryParams.set('author', params.author.trim())
  }
  if (params.release_year) {
    queryParams.set('release_year', String(params.release_year))
  }
  if (params.sort_by?.trim()) {
    queryParams.set('sort_by', params.sort_by.trim())
  }
  if (params.sort_order?.trim()) {
    queryParams.set('sort_order', params.sort_order.trim())
  }
  if (params.page) {
    queryParams.set('page', String(params.page))
  }
  if (params.limit) {
    queryParams.set('limit', String(params.limit))
  }

  return request<MangaItem[]>(`/manga/search?${queryParams.toString()}`, { signal })
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

// ── Library API methods ─────────────────────────────────────

const GUEST_LIBRARY_STORAGE_KEY = 'onigiri_guest_library'

function getGuestLibrary(): MangaItem[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(GUEST_LIBRARY_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveGuestLibrary(items: MangaItem[]): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(GUEST_LIBRARY_STORAGE_KEY, JSON.stringify(items))
  } catch {
    // Ignore storage quota errors
  }
}

export async function fetchLibrary(signal?: AbortSignal): Promise<MangaItem[]> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    return getGuestLibrary()
  }

  return request<MangaItem[]>('/library', { signal })
}

export async function fetchLibraryIds(signal?: AbortSignal): Promise<number[]> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    return getGuestLibrary().map((m) => m.id)
  }

  return request<number[]>('/library/ids', { signal })
}

export async function addToLibrary(manga: MangaItem): Promise<void> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    const current = getGuestLibrary()
    if (!current.some((item) => item.id === manga.id)) {
      saveGuestLibrary([manga, ...current])
    }
    return
  }

  await request<void>(`/library/${encodeURIComponent(String(manga.id))}`, {
    method: 'POST',
  })
}

export async function removeFromLibrary(mangaId: number): Promise<void> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    const current = getGuestLibrary()
    saveGuestLibrary(current.filter((item) => item.id !== mangaId))
    return
  }

  await request<void>(`/library/${encodeURIComponent(String(mangaId))}`, {
    method: 'DELETE',
  })
}
