import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  BookOpen,
  CheckCircle2,
  Clock,
  Compass,
  Flame,
  RefreshCw,
  Search,
  Sparkles,
} from 'lucide-react'
import ServerStatus from '../components/ServerStatus'
import CollectionRibbon from '../components/CollectionRibbon'
import ContinueReadingRibbon from '../components/ContinueReadingRibbon'
import { useServerHealth } from '../hooks/useServerHealth'
import { useLibrary } from '../context/LibraryContext'
import { fetchHomepageData, getGuestHistory } from '../services/api'
import type { HomepageData, ReadingHistoryItem } from '../types/manga'

export default function HomePage() {
  const { state: serverState, refresh: refreshServer } = useServerHealth()
  const { starredIds } = useLibrary()

  const [homepageData, setHomepageData] = useState<HomepageData | null>(null)
  const [continueReading, setContinueReading] = useState<ReadingHistoryItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      // Gather guest history + library IDs for transparent personalization
      const guestHistory = getGuestHistory()
      const guestMangaIds = new Set<number>()
      starredIds.forEach((id) => guestMangaIds.add(id))
      guestHistory.forEach((item) => guestMangaIds.add(item.manga_id))

      const data = await fetchHomepageData(
        guestMangaIds.size > 0 ? Array.from(guestMangaIds) : undefined
      )
      setHomepageData(data)

      // Merge backend history (if authorized Telegram user) with local guest history
      if (data.continue_reading && data.continue_reading.length > 0) {
        setContinueReading(data.continue_reading.slice(0, 8))
      } else if (guestHistory.length > 0) {
        setContinueReading(guestHistory.slice(0, 8))
      } else {
        setContinueReading([])
      }
    } catch {
      setError('Не удалось загрузить подборки. Проверьте соединение с сервером.')
    } finally {
      setIsLoading(false)
    }
  }, [starredIds])

  useEffect(() => {
    loadData()
  }, [loadData])

  return (
    <div className="px-4 pt-6 pb-20 max-w-5xl mx-auto">
      {/* Header */}
      <header className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-accent/20 flex items-center justify-center shadow-xs">
            <BookOpen size={20} className="text-accent" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-text-primary leading-tight">Onigiri</h1>
            <p className="text-[10px] text-text-secondary">Онлайн-читалка манги</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ServerStatus state={serverState} onRetry={refreshServer} />
          <span className="text-[11px] text-text-secondary bg-surface px-2.5 py-0.5 rounded-full border border-white/5 font-mono">
            v0.1.0
          </span>
        </div>
      </header>

      {/* Quick Search trigger banner */}
      <Link
        to="/search"
        className="flex items-center gap-3 bg-surface hover:bg-surface-secondary text-text-secondary rounded-xl px-4 py-3 mb-5 border border-white/5 hover:border-accent/30 transition-all cursor-pointer shadow-xs active:scale-[0.99]"
      >
        <Search size={18} className="text-accent shrink-0" />
        <span className="text-sm">Искать мангу в каталоге...</span>
      </Link>

      {/* Welcome banner */}
      <section className="bg-surface/80 rounded-2xl p-4 mb-6 border border-white/5 shadow-xs">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/15 flex items-center justify-center shrink-0 mt-0.5">
            <Sparkles size={18} className="text-accent" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary mb-0.5">
              Добро пожаловать в Onigiri
            </h2>
            <p className="text-xs text-text-secondary leading-relaxed">
              Читай мангу на русском языке с удобной мобильной навигацией и персональными подборками прямо в Telegram.
            </p>
          </div>
        </div>
      </section>

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="space-y-8 animate-pulse">
          {[1, 2, 3].map((idx) => (
            <div key={idx} className="space-y-3">
              <div className="flex justify-between items-center px-1">
                <div className="h-5 bg-white/5 rounded-md w-40" />
                <div className="h-4 bg-white/5 rounded-md w-14" />
              </div>
              <div className="flex gap-3 overflow-hidden">
                {[1, 2, 3, 4].map((cIdx) => (
                  <div key={cIdx} className="w-32 sm:w-36 aspect-[3/4] bg-white/5 rounded-xl shrink-0" />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Error state with retry */}
      {error && !isLoading && (
        <div className="p-6 bg-surface/50 border border-white/5 rounded-2xl text-center my-6">
          <p className="text-xs text-rose-400 mb-3">{error}</p>
          <button
            type="button"
            onClick={loadData}
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-accent hover:bg-accent/90 text-white text-xs font-semibold rounded-xl transition-all cursor-pointer shadow-xs"
          >
            <RefreshCw size={14} />
            <span>Повторить</span>
          </button>
        </div>
      )}

      {/* Dynamic Content Sections */}
      {!isLoading && homepageData && (
        <>
          {/* E. Continue Reading (if history or progress exists) */}
          <ContinueReadingRibbon items={continueReading} />

          {/* C. Personalized Recommendations: Манга в вашем стиле */}
          <CollectionRibbon
            id={homepageData.for_you.id}
            title={homepageData.for_you.title}
            subtitle={homepageData.for_you.subtitle}
            seeAllUrl={homepageData.for_you.see_all_url}
            icon={Sparkles}
            items={homepageData.for_you.items}
          />

          {/* B. Popular Ongoing: Популярные онгоинги */}
          <CollectionRibbon
            id={homepageData.popular_ongoing.id}
            title={homepageData.popular_ongoing.title}
            subtitle={homepageData.popular_ongoing.subtitle}
            seeAllUrl={homepageData.popular_ongoing.see_all_url}
            icon={Flame}
            items={homepageData.popular_ongoing.items}
          />

          {/* A. Popular Completed: Популярное завершённое */}
          <CollectionRibbon
            id={homepageData.popular_completed.id}
            title={homepageData.popular_completed.title}
            subtitle={homepageData.popular_completed.subtitle}
            seeAllUrl={homepageData.popular_completed.see_all_url}
            icon={CheckCircle2}
            items={homepageData.popular_completed.items}
          />

          {/* D. Recently Updated: Недавно обновлённые */}
          <CollectionRibbon
            id={homepageData.recently_updated.id}
            title={homepageData.recently_updated.title}
            subtitle={homepageData.recently_updated.subtitle}
            seeAllUrl={homepageData.recently_updated.see_all_url}
            icon={Clock}
            items={homepageData.recently_updated.items}
          />

          {/* G. Recently Added: Недавно добавленные */}
          <CollectionRibbon
            id={homepageData.recently_added.id}
            title={homepageData.recently_added.title}
            subtitle={homepageData.recently_added.subtitle}
            seeAllUrl={homepageData.recently_added.see_all_url}
            icon={Compass}
            items={homepageData.recently_added.items}
          />
        </>
      )}
    </div>
  )
}
