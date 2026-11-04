import { BookOpen } from 'lucide-react'

export default function LibraryPage() {
  return (
    <div className="px-4 pt-6">
      <header className="mb-6">
        <h1 className="text-xl font-bold text-text-primary">Библиотека</h1>
      </header>

      <div className="flex flex-col items-center justify-center py-20">
        <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mb-4">
          <BookOpen size={32} className="text-accent/50" />
        </div>
        <h2 className="text-base font-semibold text-text-primary mb-1">
          Твоя библиотека
        </h2>
        <p className="text-sm text-text-secondary text-center max-w-[260px]">
          Сохранённая манга будет отображаться здесь
        </p>
      </div>
    </div>
  )
}
