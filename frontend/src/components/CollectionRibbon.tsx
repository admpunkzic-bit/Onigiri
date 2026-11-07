import type { ComponentType } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import MangaCard from './MangaCard'
import type { MangaItem } from '../types/manga'

interface CollectionRibbonProps {
  id: string
  title: string
  subtitle?: string | null
  seeAllUrl?: string | null
  icon: ComponentType<{ size?: number; className?: string }>
  items: MangaItem[]
}

export default function CollectionRibbon({
  id,
  title,
  subtitle,
  seeAllUrl,
  icon: Icon,
  items,
}: CollectionRibbonProps) {
  if (!items || items.length === 0) {
    return null
  }

  return (
    <section className="mb-7" data-collection-id={id}>
      {/* Ribbon Header */}
      <div className="flex items-end justify-between mb-3 px-0.5">
        <div className="min-w-0 flex-1 pr-2">
          <div className="flex items-center gap-2">
            <Icon size={16} className="text-accent shrink-0" />
            <h2 className="text-base font-bold text-text-primary truncate">
              {title}
            </h2>
          </div>
          {subtitle && (
            <p className="text-[11px] text-text-secondary mt-0.5 line-clamp-1">
              {subtitle}
            </p>
          )}
        </div>

        {seeAllUrl && (
          <Link
            to={seeAllUrl}
            className="inline-flex items-center gap-0.5 text-xs text-accent hover:text-accent/80 font-medium shrink-0 transition-colors cursor-pointer py-0.5"
            title={`Смотреть все в подборке «${title}»`}
          >
            <span>Смотреть все</span>
            <ChevronRight size={14} />
          </Link>
        )}
      </div>

      {/* Horizontal Carousel */}
      <div className="flex gap-3 overflow-x-auto pb-2 pt-0.5 px-0.5 -mx-0.5 scrollbar-none snap-x snap-mandatory">
        {items.map((manga) => (
          <div
            key={manga.id}
            className="w-32 sm:w-36 md:w-40 shrink-0 snap-start"
          >
            <MangaCard manga={manga} />
          </div>
        ))}
      </div>
    </section>
  )
}
