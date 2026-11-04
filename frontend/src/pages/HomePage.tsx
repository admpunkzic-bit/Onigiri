import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Compass, History, Search, Sparkles } from 'lucide-react'
import MangaGrid from '../components/MangaGrid'
import ServerStatus from '../components/ServerStatus'
import { useServerHealth } from '../hooks/useServerHealth'
import { fetchMangaSearch } from '../services/api'
import type { MangaItem } from '../types/manga'

const STORAGE_KEY_RECENT = 'onigiri_recent_manga'

const FEATURED_TOPICS = [
  { label: 'Берсерк', query: 'Берсерк' },
  { label: 'Атака титанов', query: 'Атака титанов' },
  { label: 'Магическая битва', query: 'Магическая битва' },
  { label: 'Человек-бензопила', query: 'Человек-бензопила' },
]

export default function HomePage() {
  const { state: serverState, refresh: refreshServer } = useServerHealth()

  const [activeTopic, setActiveTopic] = useState(FEATURED_TOPICS[0].query)
  const [catalogItems, setCatalogItems] = useState<MangaItem[]>([])
  const [recentItems] = useState<MangaItem[]>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_RECENT)
      if (stored) {
        const parsed: MangaItem[] = JSON.parse(stored)
        return parsed.slice(0, 6)
      }
    } catch {
      // Ignore localStorage read errors
    }
    return []
  })
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 2. Fetch catalog items for current featured topic
  const loadCatalog = async (topicQuery: string) => {
    setIsLoading(true)
    setError(null)

    try {
      const items = await fetchMangaSearch({ q: topicQuery, limit: 12 })
      setCatalogItems(items)
    } catch {
      setError('Не удалось загрузить каталог. Проверьте соединение с сервером.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadCatalog(activeTopic)
  }, [activeTopic])

  return (
    <div className="px-4 pt-6">
      {/* Header */}
      <header className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-accent/20 flex items-center justify-center">
            <BookOpen size={20} className="text-accent" />
          </div>
          <h1 className="text-xl font-bold text-text-primary">Onigiri</h1>
        </div>
        <div className="flex items-center gap-2">
          <ServerStatus state={serverState} onRetry={refreshServer} />
          <span className="text-xs text-text-secondary bg-surface px-3 py-1 rounded-full">
            v0.1.0
          </span>
        </div>
      </header>

      {/* Quick Search trigger banner */}
      <Link
        to="/search"
        className="flex items-center gap-3 bg-surface hover:bg-surface-secondary text-text-secondary rounded-xl px-4 py-3 mb-5 border border-white/5 transition-colors cursor-pointer"
      >
        <Search size={18} className="text-accent shrink-0" />
        <span className="text-sm">Искать мангу в каталоге...</span>
      </Link>

      {/* Welcome banner */}
      <section className="bg-surface rounded-2xl p-4 mb-6 border border-white/5">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center shrink-0 mt-0.5">
            <Sparkles size={18} className="text-accent" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary mb-0.5">
              Добро пожаловать в Onigiri
            </h2>
            <p className="text-xs text-text-secondary leading-relaxed">
              Читай мангу на русском языке с удобной мобильной навигацией прямо в Telegram.
            </p>
          </div>
        </div>
      </section>

      {/* Recent Manga Section (if available) */}
      {recentItems.length > 0 && (
        <section className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-1.5">
              <History size={16} className="text-accent" />
              <h2 className="text-sm font-semibold text-text-primary">
                Недавно найденные
              </h2>
            </div>
            <Link
              to="/search"
              className="text-xs text-accent hover:underline font-medium"
            >
              Найти ещё
            </Link>
          </div>

          <div className="grid grid-cols-3 gap-3">
            {recentItems.slice(0, 3).map((item) => (
              <MangaGrid
                key={item.id}
                items={[item]}
                isLoading={false}
              />
            ))}
          </div>
        </section>
      )}

      {/* Main Catalog Section */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-1.5">
            <Compass size={16} className="text-accent" />
            <h2 className="text-sm font-semibold text-text-primary">
              Каталог произведений
            </h2>
          </div>
          <span className="text-xs text-text-secondary">
            {catalogItems.length > 0 ? `${catalogItems.length} тайтлов` : ''}
          </span>
        </div>

        {/* Category switcher chips */}
        <div className="flex items-center gap-2 overflow-x-auto pb-2 mb-3 scrollbar-none">
          {FEATURED_TOPICS.map((topic) => {
            const isActive = activeTopic === topic.query
            return (
              <button
                key={topic.query}
                onClick={() => setActiveTopic(topic.query)}
                className={`text-xs px-3 py-1.5 rounded-full shrink-0 transition-all cursor-pointer font-medium ${
                  isActive
                    ? 'bg-accent text-white shadow-xs shadow-accent/30'
                    : 'bg-surface hover:bg-surface-secondary text-text-secondary border border-white/5'
                }`}
              >
                {topic.label}
              </button>
            )
          })}
        </div>

        {/* Real Manga Grid */}
        <MangaGrid
          items={catalogItems}
          isLoading={isLoading}
          error={error}
          emptyMessage="Произведения не найдены"
          onRetry={() => loadCatalog(activeTopic)}
        />
      </section>
    </div>
  )
}
