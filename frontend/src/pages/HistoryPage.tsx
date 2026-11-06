import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  BookOpen,
  Clock,
  Play,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react'
import type { ReadingHistoryItem } from '../types/manga'
import {
  clearReadingHistory,
  deleteReadingHistoryItem,
  fetchReadingHistory,
} from '../services/api'

function resolveCoverUrl(url?: string | null): string | null {
  if (!url) return null
  if (url.startsWith('https://uploads.mangadex.org/') || url.includes('manga-chan.me')) {
    const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
    return `${apiBase}/manga/cover/proxy?url=${encodeURIComponent(url)}`
  }
  return url
}

function formatRelativeDate(isoString: string): string {
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return ''
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMinutes = Math.floor(diffMs / (1000 * 60))
    const diffHours = Math.floor(diffMinutes / 60)
    const diffDays = Math.floor(diffHours / 24)

    if (diffMinutes < 1) return 'Только что'
    if (diffMinutes < 60) return `${diffMinutes} мин. назад`
    if (diffHours < 24) {
      if (now.getDate() === date.getDate()) {
        const timeStr = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
        return `Сегодня, ${timeStr}`
      }
      return `${diffHours} ч. назад`
    }
    if (diffDays === 1) {
      const timeStr = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
      return `Вчера, ${timeStr}`
    }
    return date.toLocaleDateString('ru-RU', {
      day: 'numeric',
      month: 'short',
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
    })
  } catch {
    return ''
  }
}

function formatChapterLabel(item: ReadingHistoryItem): string {
  const parts: string[] = []
  if (item.volume_number != null) {
    parts.push(`Том ${item.volume_number}`)
  }
  if (item.chapter_number != null) {
    parts.push(`Гл. ${item.chapter_number}`)
  } else {
    parts.push('Глава')
  }
  if (item.chapter_title && item.chapter_title.trim()) {
    parts.push(`— ${item.chapter_title.trim()}`)
  }
  return parts.join(' ')
}

export default function HistoryPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<ReadingHistoryItem[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [isClearModalOpen, setIsClearModalOpen] = useState<boolean>(false)
  const [isClearing, setIsClearing] = useState<boolean>(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const loadHistory = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await fetchReadingHistory()
      setItems(data)
    } catch (err) {
      console.error('Failed to load reading history:', err)
      setError('Не удалось загрузить историю чтения')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const handleDeleteItem = async (e: React.MouseEvent, item: ReadingHistoryItem) => {
    e.preventDefault()
    e.stopPropagation()
    const targetId = item.manga_id
    setDeletingId(targetId)

    // Optimistic removal
    setItems((prev) => prev.filter((i) => i.manga_id !== targetId))

    try {
      await deleteReadingHistoryItem(item.manga_slug || targetId)
    } catch (err) {
      console.error('Failed to delete history item:', err)
      // Re-fetch on error to ensure sync
      loadHistory()
    } finally {
      setDeletingId(null)
    }
  };

  const handleClearAll = async () => {
    setIsClearing(true)
    try {
      await clearReadingHistory()
      setItems([])
      setIsClearModalOpen(false)
    } catch (err) {
      console.error('Failed to clear reading history:', err)
      setError('Не удалось очистить историю чтения')
    } finally {
      setIsClearing(false)
    }
  }

  const handleResume = (item: ReadingHistoryItem) => {
    const slugOrId = item.manga_slug || item.manga_id
    navigate(`/manga/${slugOrId}/chapter/${item.chapter_id}`, {
      state: { initialPage: item.page_number },
    })
  }

  const countText =
    items.length === 1
      ? 'произведение'
      : items.length >= 2 && items.length <= 4
        ? 'произведения'
        : 'произведений'

  return (
    <div className="px-4 pt-6 pb-24 max-w-4xl mx-auto">
      {/* Page Header */}
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-text-primary">История</h1>
          <p className="text-xs text-text-secondary mt-0.5">
            {isLoading ? 'Загрузка...' : `${items.length} ${countText}`}
          </p>
        </div>

        {items.length > 0 && !isLoading && (
          <button
            type="button"
            onClick={() => setIsClearModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
            title="Очистить историю"
          >
            <Trash2 size={14} />
            <span>Очистить</span>
          </button>
        )}
      </header>

      {/* Main Content Area */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, idx) => (
            <div
              key={idx}
              className="bg-surface rounded-xl p-3 border border-white/5 flex gap-3.5 animate-pulse"
            >
              <div className="w-16 sm:w-20 aspect-[3/4] bg-white/5 rounded-lg flex-shrink-0" />
              <div className="flex-1 py-1 space-y-2">
                <div className="h-4 bg-white/10 rounded w-3/4" />
                <div className="h-3 bg-white/5 rounded w-1/2" />
                <div className="h-2 bg-white/5 rounded w-full mt-4" />
                <div className="h-3 bg-white/5 rounded w-1/4 mt-2" />
              </div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="py-12 px-4 flex flex-col items-center justify-center text-center bg-surface/50 rounded-2xl border border-red-500/10">
          <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center mb-3 text-red-400">
            <AlertCircle size={24} />
          </div>
          <h3 className="text-sm font-semibold text-text-primary mb-1">{error}</h3>
          <p className="text-xs text-text-secondary max-w-[260px] mb-4">
            Проверьте соединение с интернетом и попробуйте снова
          </p>
          <button
            type="button"
            onClick={loadHistory}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-accent text-white text-xs font-medium hover:bg-accent/90 transition-all active:scale-95 cursor-pointer shadow-lg shadow-accent/20"
          >
            <RefreshCw size={14} />
            <span>Повторить</span>
          </button>
        </div>
      ) : items.length > 0 ? (
        <div className="space-y-3">
          {items.map((item) => {
            const coverSrc = resolveCoverUrl(item.cover_url)
            const chapterText = formatChapterLabel(item)
            const dateText = formatRelativeDate(item.updated_at)
            const hasProgressPercent =
              item.total_pages && item.total_pages > 0 && item.page_number > 0
            const progressPercent = hasProgressPercent
              ? Math.min(100, Math.round((item.page_number / item.total_pages!) * 100))
              : null

            return (
              <div
                key={`${item.manga_id}_${item.chapter_id}`}
                className="group relative bg-surface hover:bg-surface/90 rounded-xl p-3 border border-white/5 hover:border-white/10 transition-all flex gap-3.5 items-stretch"
              >
                {/* Manga Cover */}
                <Link
                  to={`/manga/${item.manga_slug || item.manga_id}`}
                  className="w-16 sm:w-20 aspect-[3/4] rounded-lg overflow-hidden bg-white/5 flex-shrink-0 relative block focus:outline-none"
                >
                  {coverSrc ? (
                    <img
                      src={coverSrc}
                      alt={item.manga_title}
                      loading="lazy"
                      className="w-full h-full object-cover transition-transform group-hover:scale-105 duration-300"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-white/20">
                      <BookOpen size={24} />
                    </div>
                  )}
                </Link>

                {/* Information */}
                <div className="flex-1 min-w-0 flex flex-col justify-between py-0.5">
                  <div>
                    <div className="flex items-start justify-between gap-2">
                      <Link
                        to={`/manga/${item.manga_slug || item.manga_id}`}
                        className="text-sm font-semibold text-text-primary hover:text-accent transition-colors line-clamp-1"
                        title={item.manga_title}
                      >
                        {item.manga_title}
                      </Link>

                      {/* Delete item button */}
                      <button
                        type="button"
                        onClick={(e) => handleDeleteItem(e, item)}
                        disabled={deletingId === item.manga_id}
                        className="text-text-secondary/60 hover:text-red-400 p-1 -mr-1 -mt-1 rounded-md hover:bg-white/5 transition-colors cursor-pointer flex-shrink-0"
                        title="Удалить из истории"
                        aria-label="Удалить из истории"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>

                    <p className="text-xs text-text-secondary mt-0.5 line-clamp-1">
                      {chapterText}
                    </p>
                  </div>

                  {/* Reading Progress */}
                  <div className="mt-2.5">
                    <div className="flex items-center justify-between text-[11px] text-text-secondary mb-1">
                      <span>
                        {hasProgressPercent
                          ? `Стр. ${item.page_number} из ${item.total_pages} (${progressPercent}%)`
                          : `Стр. ${item.page_number}`}
                      </span>
                      {dateText && (
                        <span className="text-text-secondary/60">{dateText}</span>
                      )}
                    </div>

                    {hasProgressPercent && (
                      <div className="w-full bg-white/5 h-1.5 rounded-full overflow-hidden">
                        <div
                          className="bg-accent h-full rounded-full transition-all duration-300"
                          style={{ width: `${progressPercent}%` }}
                        />
                      </div>
                    )}

                    {/* Resume Button */}
                    <div className="mt-2.5 flex justify-end">
                      <button
                        type="button"
                        onClick={() => handleResume(item)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent/15 text-accent text-xs font-medium hover:bg-accent hover:text-white transition-all active:scale-95 cursor-pointer"
                      >
                        <Play size={12} className="fill-current" />
                        <span>Продолжить</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        /* Empty State */
        <div className="flex flex-col items-center justify-center py-20 px-4 text-center">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mb-4">
            <Clock size={32} className="text-accent/50" />
          </div>
          <h2 className="text-base font-semibold text-text-primary mb-1">
            История чтения пуста
          </h2>
          <p className="text-sm text-text-secondary max-w-[280px] mb-6">
            Здесь появятся произведения, главы которых вы откроете в читалке
          </p>
          <button
            type="button"
            onClick={() => navigate('/search')}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-accent text-white text-xs font-medium hover:bg-accent/90 transition-all active:scale-95 cursor-pointer shadow-lg shadow-accent/20"
          >
            <Search size={16} />
            Найти мангу
          </button>
        </div>
      )}

      {/* Clear Confirmation Modal */}
      {isClearModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
          <div className="bg-surface border border-white/10 rounded-2xl p-5 max-w-sm w-full shadow-2xl space-y-4">
            <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center text-red-400 mx-auto">
              <Trash2 size={24} />
            </div>

            <div className="text-center space-y-1">
              <h3 className="text-base font-semibold text-text-primary">
                Очистить историю?
              </h3>
              <p className="text-xs text-text-secondary leading-relaxed">
                Вы уверены, что хотите удалить всю историю чтения? Это действие нельзя отменить.
              </p>
            </div>

            <div className="flex gap-2.5 pt-1">
              <button
                type="button"
                onClick={() => setIsClearModalOpen(false)}
                disabled={isClearing}
                className="flex-1 py-2.5 px-4 rounded-xl border border-white/10 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-white/5 transition-colors cursor-pointer"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleClearAll}
                disabled={isClearing}
                className="flex-1 py-2.5 px-4 rounded-xl bg-red-500 text-white text-xs font-medium hover:bg-red-600 transition-colors cursor-pointer disabled:opacity-50"
              >
                {isClearing ? 'Очистка...' : 'Очистить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
