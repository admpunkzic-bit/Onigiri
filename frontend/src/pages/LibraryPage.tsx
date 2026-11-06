import { useNavigate } from 'react-router-dom'
import { BookOpen, Search } from 'lucide-react'
import MangaGrid from '../components/MangaGrid'
import { useLibrary } from '../context/LibraryContext'

export default function LibraryPage() {
  const navigate = useNavigate()
  const { libraryItems, isLoading } = useLibrary()

  const countText =
    libraryItems.length === 1
      ? 'произведение'
      : libraryItems.length >= 2 && libraryItems.length <= 4
      ? 'произведения'
      : 'произведений'

  return (
    <div className="px-4 pt-6 pb-24 max-w-4xl mx-auto">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Библиотека</h1>
          <p className="text-xs text-text-secondary mt-0.5">
            {isLoading ? 'Загрузка...' : `${libraryItems.length} ${countText}`}
          </p>
        </div>
      </header>

      {isLoading ? (
        <MangaGrid items={[]} isLoading={true} />
      ) : libraryItems.length > 0 ? (
        <MangaGrid items={libraryItems} isLoading={false} />
      ) : (
        <div className="flex flex-col items-center justify-center py-20 px-4 text-center">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mb-4">
            <BookOpen size={32} className="text-accent/50" />
          </div>
          <h2 className="text-base font-semibold text-text-primary mb-1">
            В библиотеке пока пусто
          </h2>
          <p className="text-sm text-text-secondary max-w-[280px] mb-6">
            Нажимай на звёздочку на карточке манги или странице произведения, чтобы сохранить её сюда
          </p>
          <button
            onClick={() => navigate('/search')}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-accent text-white text-xs font-medium hover:bg-accent/90 transition-all active:scale-95 cursor-pointer shadow-lg shadow-accent/20"
          >
            <Search size={16} />
            Найти мангу
          </button>
        </div>
      )}
    </div>
  )
}
