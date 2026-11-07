import { useEffect, useMemo, useState } from 'react'
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
  RotateCcw,
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
  resolveCoverUrl,
} from '../services/api'
import type { ChapterItem, MangaDetail, ReadingProgress, TranslationVariant } from '../types/manga'
import { useLibrary } from '../context/LibraryContext'
import TranslationSelector from '../components/TranslationSelector'

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

function pluralizeChapters(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return 'глава'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'главы'
  return 'глав'
}

interface VolumeGroup {
  id: string
  volume: number | null
  title: string
  chapters: ChapterItem[]
}

function groupChaptersByVolume(chapters: ChapterItem[]): VolumeGroup[] {
  if (chapters.length === 0) return []

  const map = new Map<number | 'none', VolumeGroup>()
  const orderOfAppearance: (number | 'none')[] = []

  for (const ch of chapters) {
    const key = ch.volume_number != null ? ch.volume_number : 'none'
    if (!map.has(key)) {
      map.set(key, {
        id: String(key),
        volume: ch.volume_number ?? null,
        title: ch.volume_number != null ? `Том ${ch.volume_number}` : 'Без тома',
        chapters: [],
      })
      orderOfAppearance.push(key)
    }
    map.get(key)!.chapters.push(ch)
  }

  return orderOfAppearance.map((k) => map.get(k)!)
}

function formatChapterNumber(num: number | null | undefined): string | null {
  if (num === null || num === undefined) return null
  return String(num)
}

export default function MangaDetailPage() {
  const { idOrSlug } = useParams<{ idOrSlug: string }>()
  const navigate = useNavigate()
  const { isStarred, toggleStar } = useLibrary()

  const [manga, setManga] = useState<MangaDetail | null>(null)
  const [chapters, setChapters] = useState<ChapterItem[]>([])
  const [translations, setTranslations] = useState<TranslationVariant[]>([])
  const [selectedTranslationId, setSelectedTranslationId] = useState<string | null>(null)
  const [isLoadingTranslation, setIsLoadingTranslation] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [coverError, setCoverError] = useState(false)
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  const [isSyncing, setIsSyncing] = useState(false)
  const [isDescExpanded, setIsDescExpanded] = useState(false)
  const [progress, setProgress] = useState<ReadingProgress | null>(null)
  const [collapsedVolumes, setCollapsedVolumes] = useState<Record<string, boolean>>({})

  const volumeGroups = useMemo(() => groupChaptersByVolume(chapters), [chapters])

  const toggleVolume = (groupKey: string) => {
    setCollapsedVolumes((prev) => ({
      ...prev,
      [groupKey]: !prev[groupKey],
    }))
  }

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
      const transList = data.translations || []
      setTranslations(transList)
      const activeTransId = data.selected_translation_id || transList[0]?.id || null
      setSelectedTranslationId(activeTransId)
      setChapters(data.chapters || [])

      try {
        const prog = await fetchReadingProgress(idOrSlug, activeTransId || undefined)
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

  const handleSelectTranslation = async (transId: string) => {
    if (transId === selectedTranslationId || isLoadingTranslation || !idOrSlug) return
    setSelectedTranslationId(transId)
    setIsLoadingTranslation(true)
    try {
      const [chs, prog] = await Promise.all([
        fetchMangaChapters(idOrSlug, sortOrder, transId),
        fetchReadingProgress(idOrSlug, transId).catch(() => null),
      ])
      setChapters(chs)
      setProgress(prog)
    } catch (err) {
      console.error('Failed to load chapters for translation:', err)
    } finally {
      setIsLoadingTranslation(false)
    }
  }

  const handleSortToggle = async () => {
    if (!idOrSlug) return
    const nextOrder = sortOrder === 'asc' ? 'desc' : 'asc'
    setSortOrder(nextOrder)
    try {
      const chs = await fetchMangaChapters(idOrSlug, nextOrder, selectedTranslationId || undefined)
      setChapters(chs)
    } catch {
      // Fallback: volume-aware client-side sort
      setChapters((prev) => {
        const hasVols = prev.some((c) => c.volume_number != null)
        const getSortKey = (ch: ChapterItem) => {
          const num = ch.chapter_number ?? 0
          if (!hasVols) return [0, num, ch.id]
          if (ch.volume_number != null) return [ch.volume_number, num, ch.id]
          if (num <= 0) return [0, num, ch.id]
          return [999999, num, ch.id]
        }
        return [...prev].sort((a, b) => {
          const [va, na, ia] = getSortKey(a)
          const [vb, nb, ib] = getSortKey(b)
          if (va !== vb) return nextOrder === 'asc' ? va - vb : vb - va
          if (na !== nb) return nextOrder === 'asc' ? na - nb : nb - na
          return nextOrder === 'asc' ? ia - ib : ib - ia
        })
      })
    }
  }

  const handleStartFromBeginning = () => {
    if (!chapters.length || !manga) return
    const sortedAsc = [...chapters].sort(
      (a, b) => (a.chapter_number ?? 0) - (b.chapter_number ?? 0)
    )
    const first = sortedAsc[0]
    if (first) {
      navigate(`/manga/${manga.slug || manga.id}/chapter/${first.id}`, {
        state: { initialPage: 1 },
      })
    }
  }

  const handleSyncChapters = async () => {
    if (!idOrSlug || isSyncing) return
    setIsSyncing(true)
    try {
      await syncMangaChapters(idOrSlug)
      const refreshedData = await fetchMangaDetail(idOrSlug, selectedTranslationId || undefined)
      setManga(refreshedData)
      setTranslations(refreshedData.translations || [])
      if (refreshedData.selected_translation_id) {
        setSelectedTranslationId(refreshedData.selected_translation_id)
      }
      setChapters(refreshedData.chapters || [])
      const prog = await fetchReadingProgress(
        idOrSlug,
        (refreshedData.selected_translation_id || selectedTranslationId) || undefined
      ).catch(() => null)
      setProgress(prog)
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

  const starred = manga ? isStarred(manga.id) : false

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

        <button
          type="button"
          onClick={() => manga && toggleStar(manga)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all active:scale-95 cursor-pointer ${
            starred
              ? 'bg-amber-400/10 text-amber-400 border border-amber-400/30'
              : 'bg-surface text-text-secondary hover:text-text-primary border border-white/10'
          }`}
          title={starred ? 'Удалить из библиотеки' : 'Добавить в библиотеку'}
          aria-label={starred ? 'Удалить из библиотеки' : 'Добавить в библиотеку'}
        >
          <Star
            size={14}
            className={starred ? 'fill-amber-400 text-amber-400' : 'text-text-secondary'}
          />
          <span>{starred ? 'В библиотеке' : 'В библиотеку'}</span>
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

            {/* Authors & Artists (Clickable) */}
            {manga.authors && manga.authors.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-text-secondary mb-3">
                <Users size={14} className="shrink-0 text-accent" />
                <div className="flex flex-wrap gap-x-1.5 gap-y-0.5 line-clamp-2">
                  {manga.authors.map((a, idx) => (
                    <button
                      key={a.id || idx}
                      type="button"
                      onClick={() => navigate(`/search?author=${encodeURIComponent(a.name)}`)}
                      className="hover:text-primary-400 hover:underline transition-colors text-left font-medium cursor-pointer"
                      title={`Найти произведения автора ${a.name}`}
                    >
                      {a.name}{idx < manga.authors.length - 1 ? ',' : ''}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Genres (Clickable chips) */}
            {manga.genres && manga.genres.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-4">
                {manga.genres.map((g) => (
                  <button
                    key={g.id}
                    type="button"
                    onClick={() => navigate(`/search?genre=${encodeURIComponent(g.slug || g.name)}`)}
                    className="text-[11px] px-2.5 py-1 rounded-lg bg-surface border border-white/5 text-text-secondary hover:text-primary-400 hover:border-primary-500/30 hover:bg-primary-500/10 transition-all cursor-pointer active:scale-95"
                    title={`Фильтровать по жанру ${g.name}`}
                  >
                    {g.name}
                  </button>
                ))}
              </div>
            )}

            {/* Action Button: Continue / Start Reading */}
            {chapters.length > 0 && (() => {
              if (progress) {
                // Authoritative chapter from loaded catalog list
                const currentChapter = chapters.find((c) => c.id === progress.chapter_id)
                const chNumber = currentChapter?.chapter_number !== undefined
                  ? currentChapter.chapter_number
                  : progress.chapter_number
                const chTitle = currentChapter?.title || progress.chapter_title

                let continueLabel = 'Продолжить чтение'
                if (chNumber !== null && chNumber !== undefined) {
                  continueLabel = `Продолжить: Глава ${formatChapterNumber(chNumber)}`
                } else if (chTitle && chTitle.trim()) {
                  continueLabel = `Продолжить: ${chTitle.trim()}`
                }

                if (progress.page_number && progress.page_number > 0) {
                  continueLabel += ` (стр. ${progress.page_number})`
                }

                return (
                  <div className="mb-4">
                    <button
                      onClick={() =>
                        navigate(
                          `/manga/${manga.slug || manga.id}/chapter/${progress.chapter_id}`,
                          { state: { initialPage: progress.page_number } }
                        )
                      }
                      className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-xs font-semibold rounded-xl shadow-lg shadow-accent/20 transition-all active:scale-[0.98] cursor-pointer"
                    >
                      <BookOpen size={16} />
                      <span>{continueLabel}</span>
                    </button>
                  </div>
                )
              }

              // No progress: Start reading button
              const sorted = [...chapters].sort(
                (a, b) => (a.chapter_number ?? 0) - (b.chapter_number ?? 0)
              )
              const firstChapter = sorted[0] || chapters[0]

              let startLabel = 'Начать читать'
              if (firstChapter) {
                if (firstChapter.chapter_number !== null && firstChapter.chapter_number !== undefined) {
                  startLabel = `Начать читать (Глава ${formatChapterNumber(firstChapter.chapter_number)})`
                } else if (firstChapter.title && firstChapter.title.trim()) {
                  startLabel = `Начать читать (${firstChapter.title.trim()})`
                }
              }

              return (
                <div className="mb-4">
                  <button
                    onClick={() => {
                      if (firstChapter) {
                        navigate(
                          `/manga/${manga.slug || manga.id}/chapter/${firstChapter.id}`,
                          { state: { initialPage: 1 } }
                        )
                      }
                    }}
                    className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-xs font-semibold rounded-xl shadow-lg shadow-accent/20 transition-all active:scale-[0.98] cursor-pointer"
                  >
                    <BookOpen size={16} />
                    <span>{startLabel}</span>
                  </button>
                </div>
              )
            })()}
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
        {/* Compact Collapsible Translation Selector (TASK 017.1) */}
        <TranslationSelector
          translations={translations}
          selectedTranslationId={selectedTranslationId}
          onSelectTranslation={handleSelectTranslation}
          isLoading={isLoadingTranslation}
        />

        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
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

            {/* Start from beginning */}
            {chapters.length > 0 && (
              <button
                onClick={handleStartFromBeginning}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface border border-white/5 rounded-xl transition-colors cursor-pointer"
                title="Перейти к первой главе выбранного перевода"
              >
                <RotateCcw size={13} />
                <span>Сначала</span>
              </button>
            )}

            {/* Sync / Refresh button */}
            <button
              onClick={handleSyncChapters}
              disabled={isSyncing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface border border-white/5 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
              title="Обновить список глав и переводов"
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
              {isSyncing ? 'Синхронизация...' : 'Синхронизировать главы'}
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {volumeGroups.map((group) => {
              const isCollapsed = Boolean(collapsedVolumes[group.title])

              return (
                <div key={group.title} className="space-y-2">
                  {/* Volume Header */}
                  <button
                    type="button"
                    onClick={() => toggleVolume(group.title)}
                    className="w-full flex items-center justify-between px-3.5 py-2.5 bg-surface/70 hover:bg-surface border border-white/5 hover:border-accent/30 rounded-xl transition-all cursor-pointer group select-none"
                  >
                    <div className="flex items-center gap-2.5">
                      <BookOpen size={14} className="text-accent group-hover:scale-105 transition-transform" />
                      <span className="text-xs font-semibold text-text-primary">
                        {group.title}
                      </span>
                      <span className="text-[11px] text-text-secondary/80 bg-white/5 px-2 py-0.5 rounded-full font-medium">
                        {group.chapters.length} {pluralizeChapters(group.chapters.length)}
                      </span>
                    </div>
                    <div className="text-text-secondary group-hover:text-text-primary transition-colors">
                      {isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                    </div>
                  </button>

                  {/* Chapters within volume */}
                  {!isCollapsed && (
                    <div className="space-y-2 pl-0.5 sm:pl-1">
                      {group.chapters.map((ch) => {
                        const formattedDate = formatDate(ch.published_at)
                        const formattedNumber = String(ch.chapter_number)
                        const isCurrentRead = progress?.chapter_id === ch.id

                        return (
                          <div
                            key={ch.id}
                            onClick={() =>
                              navigate(
                                `/manga/${manga.slug || manga.id}/chapter/${ch.id}`,
                                { state: { initialPage: 1 } }
                              )
                            }
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                navigate(
                                  `/manga/${manga.slug || manga.id}/chapter/${ch.id}`,
                                  { state: { initialPage: 1 } }
                                )
                              }
                            }}
                            className={`w-full text-left bg-surface hover:bg-surface/80 active:scale-[0.99] border ${
                              isCurrentRead ? 'border-accent/60 bg-accent/5' : 'border-white/5'
                            } hover:border-accent/30 rounded-xl p-3.5 transition-all flex items-center justify-between group cursor-pointer`}
                          >
                            <div className="flex-1 min-w-0 pr-3">
                              <div className="flex items-center gap-2 mb-1">
                                <span className={`text-xs font-semibold ${
                                  isCurrentRead ? 'text-accent' : 'text-text-primary'
                                } group-hover:text-accent transition-colors`}>
                                  Глава {formattedNumber}
                                </span>
                                {ch.volume_number != null && (
                                  <span className="text-[10px] text-text-secondary bg-white/5 px-1.5 py-0.5 rounded">
                                    Том {ch.volume_number}
                                  </span>
                                )}
                                {isCurrentRead && (
                                  <span className="text-[10px] text-accent bg-accent/15 px-1.5 py-0.5 rounded font-medium">
                                    Читаете сейчас
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
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
