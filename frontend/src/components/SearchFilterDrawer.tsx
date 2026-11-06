import { useState } from 'react'
import { Filter, RotateCcw, X } from 'lucide-react'

export interface GenreOption {
  id: number
  name: string
  slug: string
}

interface SearchFilterDrawerProps {
  isOpen: boolean
  onClose: () => void
  genres: GenreOption[]
  selectedGenres: string[]
  onToggleGenre: (slug: string) => void
  selectedType: string
  onSelectType: (type: string) => void
  selectedStatus: string
  onSelectStatus: (status: string) => void
  selectedSort: string
  onSelectSort: (sort: string) => void
  onResetAll: () => void
}

const TYPE_OPTIONS = [
  { value: '', label: 'Все типы' },
  { value: 'manga', label: 'Манга' },
  { value: 'manhwa', label: 'Манхва' },
  { value: 'manhua', label: 'Маньхуа' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'Любой статус' },
  { value: 'ongoing', label: 'Онгоинг' },
  { value: 'completed', label: 'Завершён' },
  { value: 'hiatus', label: 'Приостановлен' },
]

const SORT_OPTIONS = [
  { value: 'popularity', label: 'По популярности' },
  { value: 'rating', label: 'По рейтингу' },
  { value: 'updated_at', label: 'По дате обновления' },
  { value: 'created_at', label: 'По новинкам' },
]

export default function SearchFilterDrawer({
  isOpen,
  onClose,
  genres,
  selectedGenres,
  onToggleGenre,
  selectedType,
  onSelectType,
  selectedStatus,
  onSelectStatus,
  selectedSort,
  onSelectSort,
  onResetAll,
}: SearchFilterDrawerProps) {
  const [genreSearch, setGenreSearch] = useState('')

  if (!isOpen) return null

  const filteredGenres = genres.filter((g) =>
    g.name.toLowerCase().includes(genreSearch.toLowerCase().trim())
  )

  const activeCount =
    selectedGenres.length +
    (selectedType ? 1 : 0) +
    (selectedStatus ? 1 : 0) +
    (selectedSort && selectedSort !== 'popularity' ? 1 : 0)

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div
        className="w-full sm:max-w-lg bg-surface border-t sm:border border-white/10 rounded-t-2xl sm:rounded-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Filter size={18} className="text-primary-400" />
            <h2 className="text-base font-semibold text-text-primary">Фильтры каталога</h2>
            {activeCount > 0 && (
              <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-primary-500/20 text-primary-400 border border-primary-500/30">
                {activeCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {activeCount > 0 && (
              <button
                type="button"
                onClick={onResetAll}
                className="flex items-center gap-1 text-xs text-text-secondary hover:text-red-400 transition-colors px-2 py-1 rounded"
                title="Сбросить все фильтры"
              >
                <RotateCcw size={13} />
                <span>Сбросить</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-text-secondary hover:text-text-primary rounded-lg hover:bg-white/5 transition-colors"
              aria-label="Закрыть"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="p-5 overflow-y-auto space-y-5 text-sm">
          {/* Manga Type */}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-2">
              Тип произведения
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {TYPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onSelectType(opt.value)}
                  className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all text-center ${
                    selectedType === opt.value
                      ? 'bg-primary-500 text-white border-primary-500 shadow-md shadow-primary-500/20'
                      : 'bg-surface-secondary border-white/5 text-text-secondary hover:text-text-primary hover:border-white/10'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Publication Status */}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-2">
              Статус перевода
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {STATUS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onSelectStatus(opt.value)}
                  className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all text-center ${
                    selectedStatus === opt.value
                      ? 'bg-primary-500 text-white border-primary-500 shadow-md shadow-primary-500/20'
                      : 'bg-surface-secondary border-white/5 text-text-secondary hover:text-text-primary hover:border-white/10'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Sort By */}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-2">
              Сортировка
            </label>
            <div className="grid grid-cols-2 gap-2">
              {SORT_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onSelectSort(opt.value)}
                  className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all text-left ${
                    selectedSort === opt.value
                      ? 'bg-primary-500/15 text-primary-400 border-primary-500/40 font-semibold'
                      : 'bg-surface-secondary border-white/5 text-text-secondary hover:text-text-primary'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Genres */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-text-secondary">
                Жанры {selectedGenres.length > 0 && `(${selectedGenres.length} выбрано)`}
              </label>
              {genres.length > 8 && (
                <input
                  type="text"
                  value={genreSearch}
                  onChange={(e) => setGenreSearch(e.target.value)}
                  placeholder="Поиск по жанрам..."
                  className="text-xs bg-surface-secondary border border-white/5 rounded-lg px-2.5 py-1 text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-primary-500/50"
                />
              )}
            </div>
            <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto pr-1">
              {filteredGenres.map((g) => {
                const isSelected = selectedGenres.includes(g.slug) || selectedGenres.includes(g.name)
                return (
                  <button
                    key={g.id}
                    type="button"
                    onClick={() => onToggleGenre(g.slug)}
                    className={`text-xs px-2.5 py-1.5 rounded-lg border transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-primary-500 text-white border-primary-500 font-medium shadow-sm'
                        : 'bg-surface-secondary border-white/5 text-text-secondary hover:text-text-primary hover:border-white/10'
                    }`}
                  >
                    {g.name}
                  </button>
                )
              })}
              {filteredGenres.length === 0 && (
                <p className="text-xs text-text-secondary py-2">Жанры не найдены</p>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/5 bg-surface flex gap-3">
          <button
            type="button"
            onClick={onClose}
            className="w-full py-2.5 bg-primary-500 hover:bg-primary-600 active:scale-[0.98] text-white font-medium text-sm rounded-xl transition-all shadow-lg shadow-primary-500/25"
          >
            Применить фильтры
          </button>
        </div>
      </div>
    </div>
  )
}

