import { BookMarked } from 'lucide-react'

/** Placeholder manga items for the catalog stub */
const placeholderItems = [
  { id: 1, title: 'Название манги', chapters: 42 },
  { id: 2, title: 'Название манги', chapters: 108 },
  { id: 3, title: 'Название манги', chapters: 25 },
  { id: 4, title: 'Название манги', chapters: 67 },
  { id: 5, title: 'Название манги', chapters: 13 },
  { id: 6, title: 'Название манги', chapters: 95 },
]

export default function CatalogStub() {
  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-text-primary">Каталог</h2>
        <span className="text-xs text-accent-secondary">Скоро</span>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {placeholderItems.map((item) => (
          <div
            key={item.id}
            className="bg-surface rounded-xl overflow-hidden border border-white/5 transition-transform active:scale-95"
          >
            {/* Placeholder cover */}
            <div className="aspect-[3/4] bg-white/5 flex items-center justify-center">
              <BookMarked size={28} className="text-text-secondary/30" />
            </div>

            {/* Info */}
            <div className="p-2">
              <p className="text-xs font-medium text-text-primary truncate">
                {item.title}
              </p>
              <p className="text-[10px] text-text-secondary mt-0.5">
                {item.chapters} глав
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* Info notice */}
      <div className="mt-4 p-3 rounded-xl bg-accent/5 border border-accent/10 text-center">
        <p className="text-xs text-text-secondary">
          Каталог манги будет доступен в следующей версии
        </p>
      </div>
    </section>
  )
}
