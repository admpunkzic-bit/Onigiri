import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, BookOpen } from 'lucide-react'

export default function MangaDetailPage() {
  const { idOrSlug } = useParams<{ idOrSlug: string }>()
  const navigate = useNavigate()

  return (
    <div className="px-4 pt-6">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary mb-6 transition-colors cursor-pointer"
      >
        <ArrowLeft size={16} />
        Назад
      </button>

      <div className="py-16 flex flex-col items-center justify-center text-center bg-surface rounded-2xl border border-white/5 p-6">
        <div className="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mb-4 text-accent">
          <BookOpen size={28} />
        </div>
        <h2 className="text-base font-semibold text-text-primary mb-1">
          Произведение
        </h2>
        <p className="text-xs text-accent font-mono bg-accent/10 px-2.5 py-1 rounded-md mb-3">
          {idOrSlug}
        </p>
        <p className="text-xs text-text-secondary max-w-[280px] leading-relaxed">
          Подробная карточка произведения и список глав станут доступны в следующем обновлении (TASK 011).
        </p>
      </div>
    </div>
  )
}
