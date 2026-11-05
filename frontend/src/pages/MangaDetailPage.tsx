import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowUpDown,
  BookOpen,
  Calendar,
  ChevronDown,
  ChevronUp,
  Eye,
  Info,
  RefreshCw,
  Search,
  Star,
  Users,
} from 'lucide-react'
import {
  ApiError,
  fetchMangaChapters,
  fetchMangaDetail,
  fetchReadingProgress,
  syncMangaChapters,
} from '../services/api'
import type { ChapterItem, MangaDetail, ReadingProgress } from '../types/manga'

function resolveCoverUrl(url?: string | null): string | null {
  if (!url) return null
  if (url.startsWith('https://uploads.mangadex.org/')) {
    const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
    return `${apiBase}/manga/cover/proxy?url=${encodeURIComponent(url)}`
  }
  return url
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) return ''
    return date.toLocaleDateString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })
  } catch {
    return ''
  }
}

export default function MangaDetailPage() {
  const { idOrSlug } = useParams<{ idOrSlug: string }>()
  const navigate = useNavigate()

  const [manga, setManga] = useState<MangaDetail | null>(null)
  const [chapters, setChapters] = useState<ChapterItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [coverError, setCoverError] = useState(false)
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  const [isSyncing, setIsSyncing] = useState(false)
  const [isDescExpanded, setIsDescExpanded] = useState(false)
  const [progress, setProgress] = useState<ReadingProgress | null>(null)

  const statusLabels: Record<string, { label: string; color: string }> = {
    ongoing: { label: 'Онгоинг', color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
    completed: { label: 'Завершён', color: 'bg-sky-500/10 text-sky-400 border-sky-500/20' },
    hiatus: { label: 'Приостановлен', color: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
    cancelled: { label: 'Отменён', color: 'bg-rose-500/10 text-rose-400 border-rose-500/20' },
  }

  const loadData = async () => {
    if (!idOrSlug) return
    setLoading(true)
    setError(null)
    setCoverError(false)

    try {
      const data = await fetchMangaDetail(idOrSlug)
      setManga(data)
      setChapters(data.chapters || [])

      try {
        const prog = await fetchReadingProgress(idOrSlug)
        setProgress(prog)
      } catch {
        // Ignore progress error
      }
    } catch (err: unknown) {
      if (err instanceof ApiError && err.statusCode === 404) {
        setError('not_found')
      } else {
        setError('network_error')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [idOrSlug])

  const handleSortToggle = async () => {
    if (!idOrSlug) return
    const nextOrder = sortOrder === 'asc' ? 'desc' : 'asc'
    setSortOrder(nextOrder)
    try {
      const chs = await fetchMangaChapters(idOrSlug, nextOrder)
      setChapters(chs)
    } catch {
      // Fallback: client-side sort
      setChapters((prev) =>
        [...prev].sort((a, b) =>
          nextOrder === 'asc'
            ? a.chapter_number - b.chapter_number
            : b.chapter_number - a.chapter_number
        )
      )
    }
  }

  const handleSyncChapters = async () => {
    if (!idOrSlug || isSyncing) return
    setIsSyncing(true)
    try {
      await syncMangaChapters(idOrSlug)
      const refreshedChapters = await fetchMangaChapters(idOrSlug, sortOrder)
      setChapters(refreshedChapters)
    } catch (e) {
      console.error('Failed to sync chapters:', e)
    } finally {
      setIsSyncing(false)
    }
  }

  // ── Loading state ──────────────────────────────────────────
  if (loading) {
    return (
      <div className="px-4 pt-6 pb-24 max-w-2xl mx-auto animate-pulse">
        <div className="h-6 w-20 bg-white/5 rounded-md mb-6" />
        <div className="flex flex-col sm:flex-row gap-5 mb-8">
          <div className="w-40 sm:w-48 aspect-[3/4] bg-white/5 rounded-xl mx-auto sm:mx-0 shrink-0" />
          <div className="flex-1 space-y-3 pt-2">
            <div className="h-7 bg-white/5 rounded-md w-3/4" />
            <div className="h-4 bg-white/5 rounded-md w-1/2" />
            <div className="flex gap-2 pt-2">
              <div className="h-6 w-16 bg-white/5 rounded-md" />
              <div className="h-6 w-16 bg-white/5 rounded-md" />
            </div>
            <div className="h-16 bg-white/5 rounded-md w-full pt-2" />
          </div>
        </div>
        <div className="space-y-3">
          <div className="h-6 bg-white/5 rounded-md w-32 mb-4" />
          <div className="h-14 bg-white/5 rounded-xl" />
          <div className="h-14 bg-white/5 rounded-xl" />
          <div className="h-14 bg-white/5 rounded-xl" />
        </div>
      </div>
    )
  }

  // ── Error & Not Found state ────────────────────────────────
  if (error || !manga) {
    const isNotFound = error === 'not_found'
    return (
      <div className="px-4 pt-6 pb-24 max-w-md mx-auto">
        <button
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary mb-6 transition-colors cursor-pointer"
        >
          <ArrowLeft size={16} />
          Назад
        </button>

        <div className="py-16 flex flex-col items-center justify-center text-center bg-surface rounded-2xl border border-white/5 p-6">
          <div className="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mb-4 text-accent">
            {isNotFound ? <Search size={28} /> : <Info size={28} />}
          </div>
          <h2 className="text-base font-semibold text-text-primary mb-1">
            {isNotFound ? 'Манга не найдена' : 'Ошибка загрузки'}
          </h2>
          <p className="text-xs text-text-secondary max-w-[280px] leading-relaxed mb-5">
            {isNotFound
              ? 'Произведение не найдено в каталоге или MangaDex.'
              : 'Не удалось получить информацию о манге. Проверьте подключение к серверу.'}
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => navigate('/search')}
              className="px-4 py-2 text-xs font-medium bg-white/10 text-text-primary rounded-xl hover:bg-white/15 transition-colors cursor-pointer"
            >
              В поиск
            </button>
            <button
              onClick={loadData}
              className="px-4 py-2 text-xs font-medium bg-accent text-white rounded-xl hover:bg-accent/90 transition-colors cursor-pointer"
            >
              Повторить
            </button>
          </div>
        </div>
      </div>
    )
  }

  const coverSrc = resolveCoverUrl(manga.cover_url)
  const statusInfo = statusLabels[manga.status?.toLowerCase()]
  const hasLongDesc = manga.description && manga.description.length > 250

  return (
    <div className="px-4 pt-6 pb-28 max-w-3xl mx-auto">
      {/* Navigation header */}
      <div className="flex items-center justify-between mb-5">
        <button
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
        >
          <ArrowLeft size={16} />
          Назад
        </button>
      </div>

      {/* Main manga card */}
      <div className="flex flex-col sm:flex-row gap-6 mb-8">
        {/* Cover */}
        <div className="w-40 sm:w-52 aspect-[3/4] bg-surface rounded-2xl overflow-hidden border border-white/5 shadow-xl mx-auto sm:mx-0 shrink-0 relative">
          {coverSrc && !coverError ? (
            <img
              src={coverSrc}
              alt={manga.title}
              onError={() => setCoverError(true)}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex flex-col items-center justify-center p-4 text-center text-text-secondary">
              <BookOpen size={36} className="mb-2 opacity-40 text-accent" />
              <span className="text-xs line-clamp-2">{manga.title}</span>
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 flex flex-col justify-between">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-text-primary leading-tight mb-1">
              {manga.title}
            </h1>

            {manga.original_title && (
              <p className="text-xs text-text-secondary mb-3 italic">
                {manga.original_title}
              </p>
            )}

            {/* Badges / Metrics */}
            <div className="flex flex-wrap items-center gap-2 mb-4">
              {statusInfo && (
                <span
                  className={`text-[11px] font-medium px-2.5 py-0.5 rounded-full border ${statusInfo.color}`}
                >
                  {statusInfo.label}
                </span>
              )}

              {manga.release_year && (
                <span className="inline-flex items-center gap-1 text-[11px] text-text-secondary bg-white/5 px-2.5 py-0.5 rounded-full border border-white/5">
                  <Calendar size={12} />
                  {manga.release_year}
                </span>
              )}

              {manga.rating > 0 && (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-400 bg-amber-400/10 px-2.5 py-0.5 rounded-full border border-amber-400/20">
                  <Star size={12} className="fill-amber-400" />
                  {manga.rating.toFixed(1)}
                </span>
              )}

              <span className="inline-flex items-center gap-1 text-[11px] text-text-secondary bg-white/5 px-2.5 py-0.5 rounded-full border border-white/5">
                <Eye size={12} />
                {manga.views_count.toLocaleString('ru-RU')}
              </span>
            </div>

            {/* Authors & Artists */}
            {manga.authors && manga.authors.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-text-secondary mb-3">
                <Users size={14} className="shrink-0 text-accent" />
                <span className="line-clamp-1">
                  {manga.authors.map((a) => a.name).join(', ')}
                </span>
              </div>
            )}

            {/* Genres */}
            {manga.genres && manga.genres.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-4">
                {manga.genres.map((g) => (
                  <span
                    key={g.id}
                    className="text-[11px] px-2.5 py-1 rounded-lg bg-surface border border-white/5 text-text-secondary"
                  >
                    {g.name}
                  </span>
                ))}
              </div>
            )}

            {/* Action Button: Continue / Start Reading */}
            {chapters.length > 0 && (
              <div className="mb-4">
                {progress ? (
                  <button
                    onClick={() =>
                      navigate(
                        `/manga/${manga.slug || manga.id}/chapter/${progress.chapter_id}`
                      )
                    }
                    className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-xs font-semibold rounded-xl shadow-lg shadow-accent/20 transition-all active:scale-[0.98] cursor-pointer"
                  >
                    <BookOpen size={16} />
                    <span>
                      Продолжить: Глава {progress.chapter_number} (стр. {progress.page_number})
                    </span>
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      const sorted = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number)
                      navigate(
                        `/manga/${manga.slug || manga.id}/chapter/${sorted[0]?.id || chapters[0].id}`
                      )
                    }}
                    className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-xs font-semibold rounded-xl shadow-lg shadow-accent/20 transition-all active:scale-[0.98] cursor-pointer"
                  >
                    <BookOpen size={16} />
                    <span>
                      Начать читать (Глава {chapters[0]?.chapter_number || 1})
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Description */}
          {manga.description && (
            <div className="bg-surface/60 rounded-xl p-3 border border-white/5 mt-2">
              <p
                className={`text-xs text-text-secondary leading-relaxed whitespace-pre-line ${
                  !isDescExpanded && hasLongDesc ? 'line-clamp-3' : ''
                }`}
              >
                {manga.description}
              </p>
              {hasLongDesc && (
                <button
                  onClick={() => setIsDescExpanded(!isDescExpanded)}
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-accent mt-2 hover:underline cursor-pointer"
                >
                  {isDescExpanded ? (
                    <>
                      Свернуть <ChevronUp size={12} />
                    </>
                  ) : (
                    <>
                      Развернуть описание <ChevronDown size={12} />
                    </>
                  )}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Chapters Section */}
      <div className="mt-8 border-t border-white/5 pt-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-text-primary">
              Русские главы
            </h2>
            <span className="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent font-medium">
              {chapters.length}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {/* Sort toggle */}
            <button
              onClick={handleSortToggle}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface border border-white/5 rounded-xl transition-colors cursor-pointer"
              title="Переключить порядок"
            >
              <ArrowUpDown size={13} />
              <span>{sortOrder === 'asc' ? 'С первых' : 'С новых'}</span>
            </button>

            {/* Sync button */}
            <button
              onClick={handleSyncChapters}
              disabled={isSyncing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface border border-white/5 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
              title="Синхронизировать главы"
            >
              <RefreshCw
                size={13}
                className={isSyncing ? 'animate-spin text-accent' : ''}
              />
              <span>{isSyncing ? 'Обновление...' : 'Обновить'}</span>
            </button>
          </div>
        </div>

        {/* Chapters List */}
        {chapters.length === 0 ? (
          <div className="py-12 flex flex-col items-center justify-center text-center bg-surface/50 rounded-2xl border border-white/5 p-6">
            <BookOpen size={32} className="text-text-secondary mb-3 opacity-40" />
            <p className="text-sm font-medium text-text-primary mb-1">
              Переводов на русский язык пока нет
            </p>
            <p className="text-xs text-text-secondary max-w-[280px] mb-4">
              Главы на русском языке не найдены или ещё не синхронизированы.
            </p>
            <button
              onClick={handleSyncChapters}
              disabled={isSyncing}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-accent text-white rounded-xl hover:bg-accent/90 transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw
                size={14}
                className={isSyncing ? 'animate-spin' : ''}
              />
              {isSyncing ? 'Синхронизация...' : 'Синхронизировать из MangaDex'}
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {chapters.map((ch) => {
              const formattedDate = formatDate(ch.published_at)
              const formattedNumber = Number.isInteger(ch.chapter_number)
                ? String(ch.chapter_number)
                : String(ch.chapter_number)

              return (
                <div
                  key={ch.id}
                  onClick={() =>
                    navigate(
                      `/manga/${manga.slug || manga.id}/chapter/${ch.id}`
                    )
                  }
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      navigate(
                        `/manga/${manga.slug || manga.id}/chapter/${ch.id}`
                      )
                    }
                  }}
                  className="w-full text-left bg-surface hover:bg-surface/80 active:scale-[0.99] border border-white/5 hover:border-accent/30 rounded-xl p-3.5 transition-all flex items-center justify-between group cursor-pointer"
                >
                  <div className="flex-1 min-w-0 pr-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-semibold text-text-primary group-hover:text-accent transition-colors">
                        Глава {formattedNumber}
                      </span>
                      {ch.volume_number && (
                        <span className="text-[10px] text-text-secondary bg-white/5 px-1.5 py-0.5 rounded">
                          Том {ch.volume_number}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2 text-xs text-text-secondary">
                      {ch.title && (
                        <span className="truncate max-w-[200px] sm:max-w-md text-text-secondary">
                          {ch.title}
                        </span>
                      )}
                      {ch.title && ch.scanlation_group && <span>•</span>}
                      {ch.scanlation_group && (
                        <span className="truncate max-w-[140px] text-accent/80 font-medium text-[11px]">
                          {ch.scanlation_group}
                        </span>
                      )}
                    </div>
                  </div>

                  {formattedDate && (
                    <span className="text-[11px] text-text-secondary shrink-0">
                      {formattedDate}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
