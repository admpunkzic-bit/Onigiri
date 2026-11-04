import { useCallback, useEffect, useState } from 'react'
import { Search, X } from 'lucide-react'
import MangaGrid from '../components/MangaGrid'
import { useDebounce } from '../hooks'
import { fetchMangaSearch } from '../services/api'
import type { MangaItem } from '../types/manga'

const POPULAR_SUGGESTIONS = [
  'Берсерк',
  'Атака титанов',
  'Магическая битва',
  'Человек-бензопила',
  'Клинок',
]

const STORAGE_KEY_RECENT = 'onigiri_recent_manga'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<MangaItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const debouncedQuery = useDebounce(query, 400)

  const performSearch = useCallback(async (searchStr: string) => {
    const clean = searchStr.trim()
    if (!clean) {
      setResults([])
      setIsLoading(false)
      setError(null)
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const items = await fetchMangaSearch({ q: clean, limit: 24 })
      setResults(items)

      // Save recent found manga to localStorage for Home Page recents
      if (items.length > 0) {
        try {
          const stored = localStorage.getItem(STORAGE_KEY_RECENT)
          const existing: MangaItem[] = stored ? JSON.parse(stored) : []
          const existingIds = new Set(existing.map((m) => m.id))
          const newUnique = items.filter((m) => !existingIds.has(m.id))
          const updated = [...newUnique, ...existing].slice(0, 12)
          localStorage.setItem(STORAGE_KEY_RECENT, JSON.stringify(updated))
        } catch {
          // Ignore localStorage errors
        }
      }
    } catch {
      setError('Не удалось выполнить поиск. Проверьте соединение с сервером.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    performSearch(debouncedQuery)
  }, [debouncedQuery, performSearch])

  const handleClear = () => {
    setQuery('')
    setResults([])
    setError(null)
  }

  const handleSelectSuggestion = (suggestion: string) => {
    setQuery(suggestion)
  }

  const hasQuery = query.trim().length > 0

  return (
    <div className="px-4 pt-6">
      <header className="mb-4">
        <h1 className="text-xl font-bold text-text-primary">Поиск</h1>
      </header>

      {/* Search Input Bar */}
      <div className="relative mb-4">
        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-text-secondary">
          <Search size={18} />
        </div>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Название манги..."
          className="w-full bg-surface text-text-primary placeholder:text-text-secondary text-sm rounded-xl pl-10 pr-10 py-3 border border-white/5 focus:outline-none focus:border-accent transition-colors"
          autoFocus={false}
        />
        {query ? (
          <button
            onClick={handleClear}
            className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Очистить"
          >
            <X size={18} />
          </button>
        ) : null}
      </div>

      {/* Popular suggestion chips when input is empty */}
      {!hasQuery && (
        <div className="mb-6">
          <p className="text-xs text-text-secondary mb-2.5 font-medium">
            Популярные запросы:
          </p>
          <div className="flex flex-wrap gap-2">
            {POPULAR_SUGGESTIONS.map((tag) => (
              <button
                key={tag}
                onClick={() => handleSelectSuggestion(tag)}
                className="text-xs bg-surface hover:bg-surface-secondary text-text-primary px-3 py-1.5 rounded-full border border-white/5 transition-colors active:scale-95 cursor-pointer"
              >
                {tag}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Content Area */}
      {!hasQuery ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mb-4 text-accent/50">
            <Search size={32} />
          </div>
          <h2 className="text-base font-semibold text-text-primary mb-1">
            Поиск манги
          </h2>
          <p className="text-xs text-text-secondary max-w-[260px] leading-relaxed">
            Введи название произведения для поиска в русскоязычном каталоге Onigiri
          </p>
        </div>
      ) : (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
              {isLoading ? 'Поиск...' : `Результаты (${results.length})`}
            </h2>
          </div>

          <MangaGrid
            items={results}
            isLoading={isLoading}
            error={error}
            emptyMessage={`По запросу «${query.trim()}» ничего не найдено`}
            onRetry={() => performSearch(query)}
          />
        </section>
      )}
    </div>
  )
}
