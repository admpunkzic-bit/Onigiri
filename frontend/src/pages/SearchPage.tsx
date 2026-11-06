import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Filter, Search, X } from 'lucide-react'
import MangaGrid from '../components/MangaGrid'
import SearchFilterDrawer, { type GenreOption } from '../components/SearchFilterDrawer'
import ActiveFilterChips from '../components/ActiveFilterChips'
import { useDebounce } from '../hooks'
import { fetchGenres, fetchMangaSearch } from '../services/api'
import type { MangaItem } from '../types/manga'

const STORAGE_KEY_RECENT = 'onigiri_recent_manga'

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  // Read initial filter values from URL search params
  const paramQuery = searchParams.get('q') || ''
  const paramAuthor = searchParams.get('author') || ''
  const paramType = searchParams.get('type') || ''
  const paramStatus = searchParams.get('status') || ''
  const paramSort = searchParams.get('sort_by') || 'popularity'
  const paramGenres = searchParams.getAll('genre')

  const [query, setQuery] = useState(paramQuery)
  const [author, setAuthor] = useState(paramAuthor)
  const [selectedType, setSelectedType] = useState(paramType)
  const [selectedStatus, setSelectedStatus] = useState(paramStatus)
  const [selectedSort, setSelectedSort] = useState(paramSort)
  const [selectedGenres, setSelectedGenres] = useState<string[]>(paramGenres)

  const [genresList, setGenresList] = useState<GenreOption[]>([])
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)

  const [results, setResults] = useState<MangaItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const debouncedQuery = useDebounce(query, 350)

  // Sync state if URL changes externally (e.g. navigation from MangaDetailPage tags)
  useEffect(() => {
    const urlQ = searchParams.get('q') || ''
    const urlAuthor = searchParams.get('author') || ''
    const urlType = searchParams.get('type') || ''
    const urlStatus = searchParams.get('status') || ''
    const urlSort = searchParams.get('sort_by') || 'popularity'
    const urlGenres = searchParams.getAll('genre')

    setQuery(urlQ)
    setAuthor(urlAuthor)
    setSelectedType(urlType)
    setSelectedStatus(urlStatus)
    setSelectedSort(urlSort)
    setSelectedGenres(urlGenres)
  }, [searchParams])

  // Load available genres once on mount
  useEffect(() => {
    fetchGenres()
      .then((data) => setGenresList(data))
      .catch(() => {
        // Fallback default genres
        setGenresList([
          { id: 1, name: 'Экшен', slug: 'action' },
          { id: 2, name: 'Комедия', slug: 'comedy' },
          { id: 3, name: 'Приключения', slug: 'adventure' },
          { id: 4, name: 'Фэнтези', slug: 'fantasy' },
          { id: 5, name: 'Романтика', slug: 'romance' },
          { id: 6, name: 'Драма', slug: 'drama' },
        ])
      })
  }, [])

  // Sync internal state back to URL query parameters
  const updateUrlParams = useCallback(
    (newQ: string, newAuthor: string, newType: string, newStatus: string, newSort: string, newGenres: string[]) => {
      const nextParams = new URLSearchParams()
      if (newQ.trim()) nextParams.set('q', newQ.trim())
      if (newAuthor.trim()) nextParams.set('author', newAuthor.trim())
      if (newType.trim()) nextParams.set('type', newType.trim())
      if (newStatus.trim()) nextParams.set('status', newStatus.trim())
      if (newSort.trim() && newSort !== 'popularity') nextParams.set('sort_by', newSort.trim())
      for (const g of newGenres) {
        if (g.trim()) nextParams.append('genre', g.trim())
      }
      setSearchParams(nextParams, { replace: true })
    },
    [setSearchParams]
  )

  // Perform search / catalog filter request
  const performSearch = useCallback(
    async (
      qVal: string,
      authorVal: string,
      typeVal: string,
      statusVal: string,
      sortVal: string,
      genresVal: string[]
    ) => {
      setIsLoading(true)
      setError(null)

      try {
        const items = await fetchMangaSearch({
          q: qVal.trim() || undefined,
          author: authorVal.trim() || undefined,
          type: typeVal.trim() || undefined,
          status: statusVal.trim() || undefined,
          sort_by: sortVal || 'popularity',
          genre: genresVal.length > 0 ? genresVal : undefined,
          limit: 24,
        })
        setResults(items)

        // Save recent discovered titles
        if (items.length > 0 && qVal.trim()) {
          try {
            const stored = localStorage.getItem(STORAGE_KEY_RECENT)
            const existing: MangaItem[] = stored ? JSON.parse(stored) : []
            const existingIds = new Set(existing.map((m) => m.id))
            const newUnique = items.filter((m) => !existingIds.has(m.id))
            const updated = [...newUnique, ...existing].slice(0, 12)
            localStorage.setItem(STORAGE_KEY_RECENT, JSON.stringify(updated))
          } catch {
            // Ignore storage errors
          }
        }
      } catch {
        setError('Не удалось загрузить произведения. Проверьте соединение с сервером.')
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  useEffect(() => {
    performSearch(debouncedQuery, author, selectedType, selectedStatus, selectedSort, selectedGenres)
  }, [debouncedQuery, author, selectedType, selectedStatus, selectedSort, selectedGenres, performSearch])

  // Filter interaction handlers
  const handleClearQuery = () => {
    setQuery('')
    updateUrlParams('', author, selectedType, selectedStatus, selectedSort, selectedGenres)
  }

  const handleClearAuthor = () => {
    setAuthor('')
    updateUrlParams(query, '', selectedType, selectedStatus, selectedSort, selectedGenres)
  }

  const handleClearType = () => {
    setSelectedType('')
    updateUrlParams(query, author, '', selectedStatus, selectedSort, selectedGenres)
  }

  const handleClearStatus = () => {
    setSelectedStatus('')
    updateUrlParams(query, author, selectedType, '', selectedSort, selectedGenres)
  }

  const handleToggleGenre = (slug: string) => {
    const updated = selectedGenres.includes(slug)
      ? selectedGenres.filter((s) => s !== slug)
      : [...selectedGenres, slug]
    setSelectedGenres(updated)
    updateUrlParams(query, author, selectedType, selectedStatus, selectedSort, updated)
  }

  const handleSelectSort = (sortVal: string) => {
    setSelectedSort(sortVal)
    updateUrlParams(query, author, selectedType, selectedStatus, sortVal, selectedGenres)
  }

  const handleResetAll = () => {
    setQuery('')
    setAuthor('')
    setSelectedType('')
    setSelectedStatus('')
    setSelectedSort('popularity')
    setSelectedGenres([])
    setSearchParams(new URLSearchParams(), { replace: true })
  }

  const activeFiltersCount =
    selectedGenres.length +
    (selectedType ? 1 : 0) +
    (selectedStatus ? 1 : 0) +
    (author ? 1 : 0) +
    (selectedSort !== 'popularity' ? 1 : 0)

  return (
    <div className="px-4 pt-6 pb-20">
      <header className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Каталог и поиск</h1>
          <p className="text-xs text-text-secondary mt-0.5">
            Произведения, авторы и расширенные фильтры
          </p>
        </div>
      </header>

      {/* Search Input Bar + Filter Trigger Button */}
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1">
          <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-text-secondary">
            <Search size={18} />
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              updateUrlParams(e.target.value, author, selectedType, selectedStatus, selectedSort, selectedGenres)
            }}
            placeholder="Название манги, альтернативное название..."
            className="w-full bg-surface text-text-primary placeholder:text-text-secondary text-sm rounded-xl pl-10 pr-10 py-3 border border-white/5 focus:outline-none focus:border-primary-500 transition-colors"
          />
          {query ? (
            <button
              type="button"
              onClick={handleClearQuery}
              className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
              aria-label="Очистить поисковый запрос"
            >
              <X size={18} />
            </button>
          ) : null}
        </div>

        {/* Filter Toggle Button */}
        <button
          type="button"
          onClick={() => setIsDrawerOpen(true)}
          className={`flex items-center gap-1.5 px-3.5 py-3 rounded-xl border text-sm font-medium transition-all cursor-pointer ${activeFiltersCount > 0
              ? 'bg-primary-500/15 border-primary-500/40 text-primary-400'
              : 'bg-surface border-white/5 text-text-secondary hover:text-text-primary hover:border-white/10'
            }`}
          title="Открыть фильтры"
        >
          <Filter size={18} />
          {activeFiltersCount > 0 && (
            <span className="text-xs font-bold w-5 h-5 rounded-full bg-primary-500 text-white flex items-center justify-center">
              {activeFiltersCount}
            </span>
          )}
        </button>
      </div>

      {/* Active Filter Chips */}
      <ActiveFilterChips
        query={query}
        onClearQuery={handleClearQuery}
        selectedGenres={selectedGenres}
        genres={genresList}
        onRemoveGenre={handleToggleGenre}
        author={author}
        onClearAuthor={handleClearAuthor}
        selectedType={selectedType}
        onClearType={handleClearType}
        selectedStatus={selectedStatus}
        onClearStatus={handleClearStatus}
        onResetAll={handleResetAll}
      />

      {/* Popular Genres Quick Selection when no query/genres selected */}
      {!query && selectedGenres.length === 0 && !author && genresList.length > 0 && (
        <div className="mb-5">
          <p className="text-xs text-text-secondary mb-2 font-medium">Популярные жанры:</p>
          <div className="flex flex-wrap gap-1.5">
            {genresList.slice(0, 8).map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => handleToggleGenre(g.slug)}
                className="text-xs bg-surface hover:bg-primary-500/15 hover:text-primary-400 hover:border-primary-500/30 text-text-secondary px-3 py-1.5 rounded-full border border-white/5 transition-all active:scale-95 cursor-pointer"
              >
                {g.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Results Grid */}
      <MangaGrid
        items={results}
        isLoading={isLoading}
        error={error}
        onRetry={() =>
          performSearch(debouncedQuery, author, selectedType, selectedStatus, selectedSort, selectedGenres)
        }
      />

      {/* Filter Drawer Component */}
      <SearchFilterDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        genres={genresList}
        selectedGenres={selectedGenres}
        onToggleGenre={handleToggleGenre}
        selectedType={selectedType}
        onSelectType={(t) => {
          setSelectedType(t)
          updateUrlParams(query, author, t, selectedStatus, selectedSort, selectedGenres)
        }}
        selectedStatus={selectedStatus}
        onSelectStatus={(s) => {
          setSelectedStatus(s)
          updateUrlParams(query, author, selectedType, s, selectedSort, selectedGenres)
        }}
        selectedSort={selectedSort}
        onSelectSort={(sortVal) => {
          handleSelectSort(sortVal)
        }}
        onResetAll={handleResetAll}
      />
    </div>
  )
}
