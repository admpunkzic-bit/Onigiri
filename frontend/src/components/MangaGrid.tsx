import { AlertCircle, RefreshCw, SearchX } from 'lucide-react'
import type { MangaItem } from '../types/manga'
import MangaCard from './MangaCard'

interface MangaGridProps {
  items: MangaItem[]
  isLoading: boolean
  error?: string | null
  emptyMessage?: string
  onRetry?: () => void
}

export default function MangaGrid({
  items,
  isLoading,
  error,
  emptyMessage = 'Ничего не найдено',
  onRetry,
}: MangaGridProps) {
  // 1. Loading state (skeletons)
  if (isLoading) {
    return (
      <div className="grid grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, idx) => (
          <div
            key={idx}
            className="bg-surface rounded-xl overflow-hidden border border-white/5 animate-pulse"
          >
            <div className="aspect-[3/4] bg-white/5" />
            <div className="p-2 space-y-1.5">
              <div className="h-3 bg-white/10 rounded w-4/5" />
              <div className="h-2 bg-white/5 rounded w-1/2" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  // 2. Error state
  if (error) {
    return (
      <div className="py-12 px-4 flex flex-col items-center justify-center text-center bg-surface/50 rounded-2xl border border-red-500/10">
        <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center mb-3 text-red-400">
          <AlertCircle size={24} />
        </div>
        <h3 className="text-sm font-semibold text-text-primary mb-1">
          Не удалось загрузить мангу
        </h3>
        <p className="text-xs text-text-secondary max-w-[260px] mb-4">
          {error}
        </p>
        {onRetry ? (
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-accent/20 hover:bg-accent/30 text-accent text-xs font-medium rounded-xl transition-colors cursor-pointer"
          >
            <RefreshCw size={14} />
            Попробовать снова
          </button>
        ) : null}
      </div>
    )
  }

  // 3. Empty state
  if (!items || items.length === 0) {
    return (
      <div className="py-16 px-4 flex flex-col items-center justify-center text-center bg-surface/30 rounded-2xl border border-white/5">
        <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center mb-3 text-text-secondary/50">
          <SearchX size={24} />
        </div>
        <p className="text-xs text-text-secondary max-w-[260px]">
          {emptyMessage}
        </p>
      </div>
    )
  }

  // 4. Success state (Manga Cards Grid)
  return (
    <div className="grid grid-cols-3 gap-3">
      {items.map((manga) => (
        <MangaCard key={manga.id} manga={manga} />
      ))}
    </div>
  )
}
