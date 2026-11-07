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
  ReadingHistoryItem,
  ReadingProgress,
} from '../types/manga'

export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL || '/api'
).replace(/http:\/\/localhost:/g, 'http://127.0.0.1:')

export function resolveCoverUrl(url?: string | null): string | null {
  if (!url) return null
  const clean = url.trim()
  if (!clean) return null
  if (clean.includes('uploads.mangadex.org') || clean.includes('manga-chan.me')) {
    return `${API_BASE_URL}/manga/cover/proxy?url=${encodeURIComponent(clean)}&v=014.4`
  }
  return clean
}

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

  // Forward MangaDex toggle state from localStorage
  try {
    const rawSettings = typeof window !== 'undefined' ? localStorage.getItem('onigiri_app_settings') : null
    if (rawSettings) {
      const parsed = JSON.parse(rawSettings)
      if (parsed.enableMangaDex === false) {
        headers['X-Enable-MangaDex'] = '0'
      } else {
        headers['X-Enable-MangaDex'] = '1'
      }
    }
  } catch {
    // Ignore storage parse errors
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
    let errorDetail = `API error: ${response.status}`
    try {
      const errJson = await response.json()
      if (errJson && errJson.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail)
      }
    } catch {
      // Ignore json parse error on non-json error responses
    }
    throw new ApiError(response.status, errorDetail)
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
  const baseUrl = API_BASE_URL.replace(/\/api\/?$/, '')
  return {
    ...data,
    pages: data.pages.map((p) => {
      let img = p.image_url
      if (!img.startsWith('http')) {
        img = baseUrl
          ? `${baseUrl}${img.startsWith('/') ? '' : '/'}${img}`
          : img.startsWith('/')
            ? img
            : `/${img}`
      }
      const sep = img.includes('?') ? '&' : '?'
      img = `${img}${sep}v=014.5`
      return {
        ...p,
        image_url: img,
      }
    }),
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

const GUEST_HISTORY_STORAGE_KEY = 'onigiri_guest_history'

function getGuestHistory(): ReadingHistoryItem[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(GUEST_HISTORY_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveGuestHistory(items: ReadingHistoryItem[]): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(GUEST_HISTORY_STORAGE_KEY, JSON.stringify(items))
  } catch {
    // Ignore storage quota errors
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
    manga_id?: number
    manga_title?: string
    manga_slug?: string
    cover_url?: string | null
    manga_status?: string | null
  }
): Promise<ReadingProgress | null> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined

  // If not in Telegram (Guest mode in browser), save to localStorage only
  if (!tgInitData || tgInitData.trim().length === 0) {
    const cleanIdOrSlug = idOrSlug.trim()
    const nowIso = new Date().toISOString()
    const targetMangaId = update.manga_id || (Number.isInteger(Number(cleanIdOrSlug)) ? Number(cleanIdOrSlug) : 0)

    const localRecord: ReadingProgress = {
      manga_id: targetMangaId,
      chapter_id: update.chapter_id,
      chapter_number: update.chapter_number ?? null,
      chapter_title: update.chapter_title ?? null,
      page_number: update.page_number,
      total_pages: update.total_pages,
      updated_at: nowIso,
    }
    try {
      localStorage.setItem(`onigiri_guest_progress_${cleanIdOrSlug}`, JSON.stringify(localRecord))
    } catch {
      // Ignore
    }

    // Also update guest reading history list
    try {
      const history = getGuestHistory()
      const existingIdx = history.findIndex(
        (h) => (targetMangaId > 0 && h.manga_id === targetMangaId) || h.manga_slug === cleanIdOrSlug
      )

      const entry: ReadingHistoryItem = {
        manga_id: targetMangaId || (existingIdx >= 0 ? history[existingIdx].manga_id : 0),
        manga_slug: update.manga_slug || (existingIdx >= 0 ? history[existingIdx].manga_slug : cleanIdOrSlug),
        manga_title: update.manga_title || (existingIdx >= 0 ? history[existingIdx].manga_title : cleanIdOrSlug),
        cover_url: update.cover_url ?? (existingIdx >= 0 ? history[existingIdx].cover_url : null),
        manga_status: update.manga_status ?? (existingIdx >= 0 ? history[existingIdx].manga_status : 'unknown'),
        chapter_id: update.chapter_id,
        chapter_number: update.chapter_number ?? null,
        chapter_title: update.chapter_title ?? null,
        page_number: update.page_number,
        total_pages: update.total_pages ?? null,
        updated_at: nowIso,
      }

      if (existingIdx >= 0) {
        history.splice(existingIdx, 1)
      }
      history.unshift(entry)
      saveGuestHistory(history)
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

// ── History API methods ─────────────────────────────────────

export async function fetchReadingHistory(signal?: AbortSignal): Promise<ReadingHistoryItem[]> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    return getGuestHistory()
  }

  return request<ReadingHistoryItem[]>('/history', { signal })
}

export async function deleteReadingHistoryItem(mangaId: number | string): Promise<void> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    const current = getGuestHistory()
    const targetStr = String(mangaId)
    const targetNum = Number(mangaId)
    const filtered = current.filter(
      (item) => String(item.manga_id) !== targetStr && item.manga_slug !== targetStr && (!Number.isInteger(targetNum) || item.manga_id !== targetNum)
    )
    saveGuestHistory(filtered)
    return
  }

  await request<void>(`/history/${encodeURIComponent(String(mangaId))}`, {
    method: 'DELETE',
  })
}

export async function clearReadingHistory(): Promise<void> {
  const tgInitData = typeof window !== 'undefined' ? window.Telegram?.WebApp?.initData : undefined
  if (!tgInitData || tgInitData.trim().length === 0) {
    if (typeof window !== 'undefined') {
      try {
        localStorage.removeItem(GUEST_HISTORY_STORAGE_KEY)
      } catch {
        // Ignore
      }
    }
    return
  }

  await request<void>('/history', {
    method: 'DELETE',
  })
}
