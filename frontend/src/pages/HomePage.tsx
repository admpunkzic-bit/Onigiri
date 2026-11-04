import { BookOpen, Sparkles } from 'lucide-react'
import CatalogStub from '../components/CatalogStub'
import ServerStatus from '../components/ServerStatus'
import { useServerHealth } from '../hooks/useServerHealth'

export default function HomePage() {
  const { state, refresh } = useServerHealth()

  return (
    <div className="px-4 pt-6">
      {/* Header */}
      <header className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-accent/20 flex items-center justify-center">
            <BookOpen size={20} className="text-accent" />
          </div>
          <h1 className="text-xl font-bold text-text-primary">Onigiri</h1>
        </div>
        <div className="flex items-center gap-2">
          <ServerStatus state={state} onRetry={refresh} />
          <span className="text-xs text-text-secondary bg-surface px-3 py-1 rounded-full">
            v0.1.0
          </span>
        </div>
      </header>

      {/* Welcome banner */}
      <section className="bg-surface rounded-2xl p-5 mb-6 border border-white/5">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center shrink-0 mt-0.5">
            <Sparkles size={20} className="text-accent" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-text-primary mb-1">
              Добро пожаловать!
            </h2>
            <p className="text-sm text-text-secondary leading-relaxed">
              Onigiri — твоя манга-читалка в Telegram. Ищи мангу, читай главы и наслаждайся.
            </p>
          </div>
        </div>
      </section>

      {/* Catalog stub */}
      <CatalogStub />
    </div>
  )
}
