import { X } from 'lucide-react'
import type { GenreOption } from './SearchFilterDrawer'

interface ActiveFilterChipsProps {
  query: string
  onClearQuery: () => void
  selectedGenres: string[]
  genres: GenreOption[]
  onRemoveGenre: (slug: string) => void
  author: string
  onClearAuthor: () => void
  selectedType: string
  onClearType: () => void
  selectedStatus: string
  onClearStatus: () => void
  onResetAll: () => void
}

const TYPE_NAMES: Record<string, string> = {
  manga: 'Манга',
  manhwa: 'Манхва',
  manhua: 'Маньхуа',
}

const STATUS_NAMES: Record<string, string> = {
  ongoing: 'Онгоинг',
  completed: 'Завершён',
  hiatus: 'Приостановлен',
  cancelled: 'Отменён',
}

export default function ActiveFilterChips({
  query,
  onClearQuery,
  selectedGenres,
  genres,
  onRemoveGenre,
  author,
  onClearAuthor,
  selectedType,
  onClearType,
  selectedStatus,
  onClearStatus,
  onResetAll,
}: ActiveFilterChipsProps) {
  const hasFilters =
    Boolean(query) ||
    selectedGenres.length > 0 ||
    Boolean(author) ||
    Boolean(selectedType) ||
    Boolean(selectedStatus)

  if (!hasFilters) return null

  const getGenreName = (slugOrName: string) => {
    const found = genres.find((g) => g.slug === slugOrName || g.name === slugOrName)
    return found ? found.name : slugOrName
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-4 animate-fade-in">
      {/* Query chip */}
      {query && (
        <span className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-primary-500/20 text-primary-300 border border-primary-500/30">
          <span>Поиск: «{query}»</span>
          <button
            type="button"
            onClick={onClearQuery}
            className="hover:text-white p-0.5"
            aria-label="Удалить поисковый запрос"
          >
            <X size={12} />
          </button>
        </span>
      )}

      {/* Author chip */}
      {author && (
        <span className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-accent/20 text-accent border border-accent/30">
          <span>Автор: {author}</span>
          <button
            type="button"
            onClick={onClearAuthor}
            className="hover:text-white p-0.5"
            aria-label="Удалить фильтр по автору"
          >
            <X size={12} />
          </button>
        </span>
      )}

      {/* Type chip */}
      {selectedType && (
        <span className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-white/10 text-text-primary border border-white/10">
          <span>{TYPE_NAMES[selectedType] || selectedType}</span>
          <button
            type="button"
            onClick={onClearType}
            className="hover:text-red-400 p-0.5"
            aria-label="Удалить фильтр типа"
          >
            <X size={12} />
          </button>
        </span>
      )}

      {/* Status chip */}
      {selectedStatus && (
        <span className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-white/10 text-text-primary border border-white/10">
          <span>{STATUS_NAMES[selectedStatus] || selectedStatus}</span>
          <button
            type="button"
            onClick={onClearStatus}
            className="hover:text-red-400 p-0.5"
            aria-label="Удалить фильтр статуса"
          >
            <X size={12} />
          </button>
        </span>
      )}

      {/* Genre chips */}
      {selectedGenres.map((slug) => (
        <span
          key={slug}
          className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-primary-500/20 text-primary-300 border border-primary-500/30"
        >
          <span>{getGenreName(slug)}</span>
          <button
            type="button"
            onClick={() => onRemoveGenre(slug)}
            className="hover:text-white p-0.5"
            aria-label={`Удалить жанр ${getGenreName(slug)}`}
          >
            <X size={12} />
          </button>
        </span>
      ))}

      {/* Reset all button */}
      <button
        type="button"
        onClick={onResetAll}
        className="text-[11px] text-text-secondary hover:text-red-400 underline underline-offset-2 px-1 transition-colors cursor-pointer"
      >
        Сбросить всё
      </button>
    </div>
  )
}

