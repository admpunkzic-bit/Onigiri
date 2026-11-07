import { Link } from 'react-router-dom'
import { History, Play, ChevronRight, BookOpen } from 'lucide-react'
import type { ReadingHistoryItem } from '../types/manga'
import { resolveCoverUrl } from '../services/api'

interface ContinueReadingRibbonProps {
  items: ReadingHistoryItem[]
}

export default function ContinueReadingRibbon({ items }: ContinueReadingRibbonProps) {
  if (!items || items.length === 0) {
    return null
  }

  return (
    <section className="mb-7" data-collection-id="continue_reading">
      {/* Header */}
      <div className="flex items-end justify-between mb-3 px-0.5">
        <div className="min-w-0 flex-1 pr-2">
          <div className="flex items-center gap-2">
            <History size={16} className="text-accent shrink-0" />
            <h2 className="text-base font-bold text-text-primary truncate">
              Продолжить чтение
            </h2>
          </div>
          <p className="text-[11px] text-text-secondary mt-0.5 line-clamp-1">
            Произведения с вашим сохранённым прогрессом
          </p>
        </div>

        <Link
          to="/history"
          className="inline-flex items-center gap-0.5 text-xs text-accent hover:text-accent/80 font-medium shrink-0 transition-colors cursor-pointer py-0.5"
          title="Смотреть всю историю чтения"
        >
          <span>Вся история</span>
          <ChevronRight size={14} />
        </Link>
      </div>

      {/* Horizontal Cards */}
      <div className="flex gap-3 overflow-x-auto pb-2 pt-0.5 px-0.5 -mx-0.5 scrollbar-none snap-x snap-mandatory">
        {items.map((item) => {
          const coverSrc = resolveCoverUrl(item.cover_url)
          const chapterLabel =
            item.chapter_number != null
              ? `Глава ${item.chapter_number}`
              : item.chapter_title?.trim() || 'Глава'

          return (
            <div
              key={`${item.manga_id}_${item.chapter_id}`}
              className="w-64 sm:w-72 shrink-0 snap-start bg-surface rounded-xl border border-white/5 hover:border-accent/30 p-2.5 transition-all group flex gap-3 shadow-xs"
            >
              {/* Cover thumbnail */}
              <Link
                to={`/manga/${item.manga_slug || item.manga_id}/chapter/${item.chapter_id}`}
                state={{ initialPage: item.page_number, translationId: item.translation_id }}
                className="w-16 sm:w-18 aspect-[3/4] rounded-lg overflow-hidden bg-white/5 shrink-0 block relative"
                title={`Продолжить чтение ${item.manga_title}`}
              >
                {coverSrc ? (
                  <img
                    src={coverSrc}
                    alt={item.manga_title}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    loading="eager"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center bg-surface-secondary">
                    <BookOpen size={18} className="text-text-secondary/50" />
                  </div>
                )}
              </Link>

              {/* Information & Action */}
              <div className="flex flex-col justify-between min-w-0 flex-1 py-0.5">
                <div>
                  <Link
                    to={`/manga/${item.manga_slug || item.manga_id}`}
                    className="text-xs font-semibold text-text-primary hover:text-accent truncate block transition-colors leading-tight"
                    title={item.manga_title}
                  >
                    {item.manga_title}
                  </Link>
                  <p className="text-[11px] text-text-secondary mt-1 truncate">
                    <span className="font-medium text-text-primary/90">{chapterLabel}</span>
                    {item.page_number > 0 && (
                      <span className="text-[10px] text-accent ml-1.5 font-medium">
                        (стр. {item.page_number}{item.total_pages ? ` / ${item.total_pages}` : ''})
                      </span>
                    )}
                  </p>
                </div>

                <Link
                  to={`/manga/${item.manga_slug || item.manga_id}/chapter/${item.chapter_id}`}
                  state={{ initialPage: item.page_number, translationId: item.translation_id }}
                  className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-white bg-accent/90 hover:bg-accent px-3 py-1.5 rounded-lg transition-all active:scale-95 w-fit mt-2 shadow-xs cursor-pointer"
                >
                  <Play size={10} className="fill-white" />
                  <span>Продолжить</span>
                </Link>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
