import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookMarked, Star } from 'lucide-react'
import type { MangaItem } from '../types/manga'
import { useLibrary } from '../context/LibraryContext'
import { resolveCoverUrl } from '../services/api'

interface MangaCardProps {
  manga: MangaItem
}

export default function MangaCard({ manga }: MangaCardProps) {
  const [imageError, setImageError] = useState(false)
  const { isStarred, toggleStar } = useLibrary()
  const starred = isStarred(manga.id)

  // Status mapping in Russian
  const statusLabels: Record<string, string> = {
    ongoing: 'Онгоинг',
    completed: 'Завершён',
    hiatus: 'Приостановлен',
    cancelled: 'Отменён',
  }

  const primaryAuthor = manga.authors?.[0]?.name
  const statusText = statusLabels[manga.status?.toLowerCase()] || null
  const coverSrc = resolveCoverUrl(manga.cover_url)

  useEffect(() => {
    setImageError(false)
  }, [coverSrc])

  return (
    <Link
      to={`/manga/${manga.slug || manga.id}`}
      className="group flex flex-col bg-surface rounded-xl overflow-hidden border border-white/5 transition-all active:scale-[0.97] hover:border-accent/30 focus:outline-none"
    >
      {/* Cover image container */}
      <div className="relative aspect-[3/4] w-full bg-white/5 overflow-hidden">
        {/* Star button */}
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            toggleStar(manga)
          }}
          className="absolute top-1.5 left-1.5 z-10 p-1.5 rounded-full bg-black/60 backdrop-blur-xs text-white/80 hover:text-white transition-all active:scale-90 cursor-pointer"
          title={starred ? 'Удалить из библиотеки' : 'Добавить в библиотеку'}
          aria-label={starred ? 'Удалить из библиотеки' : 'Добавить в библиотеку'}
        >
          <Star
            size={14}
            className={starred ? 'fill-amber-400 text-amber-400' : 'text-white/80 hover:text-white'}
          />
        </button>
        {coverSrc && !imageError ? (
          <img
            src={coverSrc}
            alt={manga.title}
            loading="eager"
            referrerPolicy="no-referrer"
            onError={() => setImageError(true)}
            className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center p-3 text-center bg-surface-secondary/50">
            <BookMarked size={28} className="text-text-secondary/40 mb-1" />
            <span className="text-[10px] text-text-secondary/60 line-clamp-2">
              {manga.title}
            </span>
          </div>
        )}

        {/* Optional year badge if available */}
        {manga.release_year ? (
          <div className="absolute top-1.5 right-1.5 bg-black/60 backdrop-blur-xs px-1.5 py-0.5 rounded text-[10px] font-medium text-text-primary">
            {manga.release_year}
          </div>
        ) : null}
      </div>

      {/* Manga details */}
      <div className="p-2 flex flex-col flex-1 justify-between">
        <div>
          <h3
            className="text-xs font-semibold text-text-primary line-clamp-2 leading-tight group-hover:text-accent transition-colors"
            title={manga.title}
          >
            {manga.title}
          </h3>
          {primaryAuthor ? (
            <p className="text-[10px] text-text-secondary truncate mt-0.5">
              {primaryAuthor}
            </p>
          ) : null}
        </div>

        {/* Status or genre tag */}
        {statusText ? (
          <p className="text-[10px] text-accent/80 font-medium mt-1">
            {statusText}
          </p>
        ) : manga.genres?.[0]?.name ? (
          <p className="text-[10px] text-text-secondary/80 truncate mt-1">
            {manga.genres[0].name}
          </p>
        ) : null}
      </div>
    </Link>
  )
}
